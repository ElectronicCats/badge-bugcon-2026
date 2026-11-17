// Sustituto mínimo de Arduino.h para compilar en la PC lógica de firmware
// que depende de config/badge_config.h (ésta sí lo incluye de verdad, para
// el firmware real). Solo define lo que badge_config.h usa fuera del
// propio Arduino: por ahora, HIGH (cfg::epaper::BUSY_ACTIVE_LEVEL).
//
// No es un stub general: si otro header necesita más símbolos de Arduino.h
// para compilar en la PC, agregarlos aquí; nunca incluir el Arduino.h real
// (arrastra el core de ESP32 completo).
#pragma once

#define HIGH 1
#define LOW 0
