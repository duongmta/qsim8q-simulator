#ifndef Q8_PROTOCOL_H
#define Q8_PROTOCOL_H

#include <stdint.h>
#include <stddef.h>
#define Q8_VERSION 1U
#define Q8_BUILD 0x00010000U
#define Q8_MAX_QUBITS 8U
#define Q8_MAX_LAYERS 20U
#define Q8_MAX_INST 256U
#define Q8_MAX_PAYLOAD (4U + 16U * Q8_MAX_INST)
#define Q8_HELLO 1U
#define Q8_RUN 2U
#define Q8_HELLO_REPLY 0x81U
#define Q8_RUN_REPLY 0x82U
#define Q8_ERROR 0xffU

static inline uint16_t rd16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static inline uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline void wr16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
}
static inline void wr32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (i * 8));
}
static inline void wr64(uint8_t *p, uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (i * 8));
}
static inline uint32_t crc_update(uint32_t crc, const uint8_t *p, size_t n) {
    while (n--) {
        crc ^= *p++;
        for (unsigned j = 0; j < 8; ++j)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320U : 0U);
    }
    return crc;
}
#endif
