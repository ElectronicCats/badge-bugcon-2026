// SPDX-License-Identifier: GPL-3.0-or-later
//
// Raw I/Q burst capture through the ESP32-S3 Wi-Fi MAC dump, under Arduino.
// Standalone feasibility sketch: it is not part of the badge firmware.
//
// The capture sequence (registers, owner value, lane select, control bits)
// follows ESPARGOS esp-sdr, main/targets/esp32s3/receiver.c, commit a8eaac1
// (https://github.com/ESPARGOS/esp-sdr, GPL-3.0-or-later).
//
// Serial commands (115200, one per line):
//   cap [n] [80|40|16]   one burst of n samples (default 4096, 80 MS/s)
//   stat [k] [n]         k bursts, one line each (default 20 x 4096)
//   raw [k]              first k samples of the last burst as "I Q gain"
//   ch <1..13>           Wi-Fi channel
//   gain auto|<0..79>    release / force the RX gain (phy_force_rx_gain)
//   rx 0|1               keep the RX chain off (control) or on
//   probe 0|1            read the bank below the window while armed
//   heap                 free heap

#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_heap_caps.h"
#include "soc/soc.h"
#include "heap_memory_layout.h"
#include <math.h>

#define WIN_BASE 0x3fcd0000u  // 64 KiB aperture the dump writes (MAC_DUMP_USAGE=4)
#define WIN_END 0x3fce0000u
#define LOW_BASE 0x3fcc0000u  // bank below: canaries only, to see what the owner bit takes
SOC_RESERVE_MEMORY_REGION(LOW_BASE, WIN_END, s3_rf_dump);

#define IQ ((volatile uint32_t*) WIN_BASE)
#define BELOW ((volatile uint32_t*) LOW_BASE)
#define LOW_WORDS 16384u
#define MAX_SAMPLES 16380u
#define SRAM_OWNER_REG 0x600c101cu  // SENSITIVE_INTERNAL_SRAM_USAGE_3_REG
#define DUMP_CTRL_REG 0x60033d5cu
#define DUMP_LANE_REG 0x60033d90u
#define CANARY 0xa5a0055au
#define GUARD(j) (0x5a5aa5a5u ^ (j))
#define LOW_PATTERN(i) (0x3c3c0000u | (i))

extern "C" {
void stop_tx_tone(unsigned);
void rom_pbus_workmode(void);
void rom_pbus_xpd_tx_off(void);
void rom_pbus_xpd_rx_on(unsigned);
void rom_pbus_xpd_rx_off(void);
void rom_set_rxclk_en(unsigned);
void set_chanfreq(unsigned, unsigned);
void phy_force_rx_gain(unsigned, unsigned);  // wraps rom_rx_gain_force
}

static uint8_t s_ch = 1;
static bool s_rx_on = true;
static bool s_probe = true;
static int s_gain = -1;  // -1: AGC
static uint32_t s_last_n = 0;

struct Burst {
  bool done;
  uint32_t us;
  uint32_t untouched;   // canaries left in the n samples
  bool guards_ok;       // words right after the n samples
  uint32_t low_bad_during;
  uint32_t low_reads;
  uint32_t low_bad_after;
};

struct Stats {
  float mi, mq, rms, dbfs;
  int peak, gmin, gmax;
};

static unsigned ch_mhz(uint8_t ch) {
  return ch == 14 ? 2484 : 2407 + 5u * ch;
}

static void front_end() {
  esp_wifi_set_channel(s_ch, WIFI_SECOND_CHAN_NONE);
  set_chanfreq(ch_mhz(s_ch), 0);
  stop_tx_tone(1);
  rom_pbus_workmode();
  rom_pbus_xpd_tx_off();
  if (s_rx_on) {
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
  } else {
    rom_set_rxclk_en(0);
    rom_pbus_xpd_rx_off();
  }
  if (s_gain >= 0)
    phy_force_rx_gain(1, (unsigned) s_gain);
  esp_rom_delay_us(3000);
}

static bool rate_bits(int msps, uint32_t* bits) {
  switch (msps) {
    case 80: *bits = 0; return true;
    case 40: *bits = 1u << 15; return true;
    case 16: *bits = 1u << 16; return true;
    default: return false;
  }
}

static Burst capture(uint32_t n, uint32_t rbits) {
  Burst b = {};
  for (uint32_t i = 0; i < n; i++) IQ[i] = CANARY;
  for (uint32_t j = 0; j < 4; j++) IQ[n + j] = GUARD(j);
  for (uint32_t i = 0; i < LOW_WORDS; i++) BELOW[i] = LOW_PATTERN(i);

  front_end();

  const uint32_t owner = REG_READ(SRAM_OWNER_REG);
  const int64_t t0 = esp_timer_get_time();
  REG_WRITE(DUMP_CTRL_REG, 0);
  REG_WRITE(DUMP_LANE_REG, 0u | (1u << 6) | (2u << 12) | (3u << 18));
  REG_WRITE(SRAM_OWNER_REG, (owner & ~15u) | 4u);
  const uint32_t ctrl = 0x80000000u | rbits | n;
  REG_WRITE(DUMP_CTRL_REG, ctrl);
  REG_WRITE(DUMP_CTRL_REG, ctrl | (1u << 19));
  REG_WRITE(DUMP_CTRL_REG, ctrl);
  uint32_t i = 0;
  while (!(REG_READ(DUMP_CTRL_REG) & (1u << 18)) && esp_timer_get_time() - t0 < 20000) {
    if (s_probe) {
      if (BELOW[i] != LOW_PATTERN(i)) b.low_bad_during++;
      b.low_reads++;
      i = (i + 97) % LOW_WORDS;
    }
  }
  b.done = (REG_READ(DUMP_CTRL_REG) & (1u << 18)) != 0;
  b.us = (uint32_t) (esp_timer_get_time() - t0);
  REG_WRITE(DUMP_CTRL_REG, 0);
  REG_WRITE(SRAM_OWNER_REG, owner);

  for (uint32_t k = 0; k < n; k++)
    if (IQ[k] == CANARY) b.untouched++;
  b.guards_ok = true;
  for (uint32_t j = 0; j < 4; j++)
    if (IQ[n + j] != GUARD(j)) b.guards_ok = false;
  for (uint32_t k = 0; k < LOW_WORDS; k++)
    if (BELOW[k] != LOW_PATTERN(k)) b.low_bad_after++;
  s_last_n = n;
  return b;
}

static int s10(uint32_t v) {
  return (v & 0x200u) ? (int) v - 1024 : (int) v;
}

static Stats stats(uint32_t n) {
  Stats s = {0, 0, 0, 0, 0, 255, 0};
  double si = 0, sq = 0, p = 0;
  for (uint32_t k = 0; k < n; k++) {
    const uint32_t w = IQ[k];
    const int I = s10(w & 0x3ffu), Q = s10((w >> 10) & 0x3ffu), g = (w >> 20) & 0xffu;
    si += I;
    sq += Q;
    p += (double) I * I + (double) Q * Q;
    if (abs(I) > s.peak) s.peak = abs(I);
    if (abs(Q) > s.peak) s.peak = abs(Q);
    if (g < s.gmin) s.gmin = g;
    if (g > s.gmax) s.gmax = g;
  }
  s.mi = si / n;
  s.mq = sq / n;
  const double ac = p / n - (double) s.mi * s.mi - (double) s.mq * s.mq;  // DC removed
  s.rms = sqrt(ac > 0 ? ac : 0);
  s.dbfs = s.rms > 0 ? 20 * log10(s.rms / 512.0) : -99;
  return s;
}

static void report(const Burst& b, uint32_t n) {
  Serial.printf("CAP ch=%u n=%lu done=%d us=%lu untouched=%lu guards=%d low_during=%lu/%lu low_after=%lu",
                s_ch, (unsigned long) n, b.done, (unsigned long) b.us, (unsigned long) b.untouched,
                b.guards_ok, (unsigned long) b.low_bad_during, (unsigned long) b.low_reads,
                (unsigned long) b.low_bad_after);
  if (b.done) {
    const Stats s = stats(n);
    Serial.printf(" dc=%.1f,%.1f rms=%.2f dbfs=%.1f peak=%d gain=%d..%d w0=%08lx w1=%08lx",
                  s.mi, s.mq, s.rms, s.dbfs, s.peak, s.gmin, s.gmax, (unsigned long) IQ[0],
                  (unsigned long) IQ[1]);
  }
  Serial.println();
}

static void handle(String line) {
  line.trim();
  char cmd[8] = {0};
  long a = -1, c = -1;
  char word[8] = {0};
  sscanf(line.c_str(), "%7s %ld %ld", cmd, &a, &c);
  sscanf(line.c_str(), "%*s %7s", word);
  const String k(cmd);

  if (k == "cap" || k == "stat") {
    const bool stat = k == "stat";
    const long reps = stat ? (a > 0 ? a : 20) : 1;
    uint32_t n = (uint32_t) ((stat ? c : a) > 0 ? (stat ? c : a) : 4096);
    if (n > MAX_SAMPLES) n = MAX_SAMPLES;
    uint32_t rb = 0;
    if (!stat && c > 0 && !rate_bits((int) c, &rb)) {
      Serial.println("ERR rate");
      return;
    }
    for (long r = 0; r < reps; r++) report(capture(n, rb), n);
    Serial.println("OK");
  } else if (k == "raw") {
    const uint32_t m = a > 0 && (uint32_t) a < s_last_n ? a : s_last_n;
    for (uint32_t i = 0; i < m; i++) {
      const uint32_t w = IQ[i];
      Serial.printf("%d %d %lu\n", s10(w & 0x3ffu), s10((w >> 10) & 0x3ffu), (unsigned long) ((w >> 20) & 0xffu));
    }
    Serial.println("OK");
  } else if (k == "ch" && a >= 1 && a <= 13) {
    s_ch = (uint8_t) a;
    Serial.println("OK");
  } else if (k == "gain") {
    if (String(word) == "auto") {
      s_gain = -1;
      phy_force_rx_gain(0, 0);
    } else if (a >= 0 && a <= 79) {
      s_gain = (int) a;
    } else {
      Serial.println("ERR gain");
      return;
    }
    Serial.println("OK");
  } else if (k == "rx" && (a == 0 || a == 1)) {
    s_rx_on = a == 1;
    Serial.println("OK");
  } else if (k == "probe" && (a == 0 || a == 1)) {
    s_probe = a == 1;
    Serial.println("OK");
  } else if (k == "heap") {
    Serial.printf("HEAP free=%u largest=%u min=%u\n", (unsigned) heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                  (unsigned) heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                  (unsigned) heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
  } else if (line.length()) {
    Serial.println("ERR cmd");
  }
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(s_ch, WIFI_SECOND_CHAN_NONE);
  delay(200);
  Serial.printf("S3DUMP ready owner=%08lx heap=%u\n", (unsigned long) REG_READ(SRAM_OWNER_REG),
                (unsigned) heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
}

void loop() {
  static String line;
  while (Serial.available()) {
    const char ch = (char) Serial.read();
    if (ch == '\n' || ch == '\r') {
      handle(line);
      line = "";
    } else {
      line += ch;
    }
  }
  delay(1);
}
