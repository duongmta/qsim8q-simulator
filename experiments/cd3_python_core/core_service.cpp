// Python <-> C/C++ core service for Chuyen de 3 experiments.
// Builds the canonical HLS source (hls/qsim8.cpp) as an ordinary C++ library and
// exposes one byte-stream entry point that speaks the same Q8PK v1 frames as the
// project protocol: header + payload + CRC32. No hardware is involved.
#include <chrono>
#include <cstring>
#include <cstdint>
#include "qsim8.cpp"   // resolved through -I: canonical hls/ or a width variant
#include "protocol.h"  // bundled Q8PK protocol definitions for the local simulator

#if defined(_WIN32)
#define Q8_EXPORT extern "C" __declspec(dllexport)
#else
#define Q8_EXPORT extern "C" __attribute__((visibility("default")))
#endif

static state_word_t g_state[NUM_STATES];
static instruction_word_t g_inst[MAX_INSTRUCTIONS];
static uint64_t g_last_core_ns = 0;

static uint32_t put_frame(uint8_t *out, uint32_t cap, uint8_t type, uint32_t id,
                          const uint8_t *payload, uint32_t size) {
    if (cap < 20u + size) return 0;
    uint8_t *h = out;
    h[0] = 'Q'; h[1] = '8'; h[2] = 'P'; h[3] = 'K';
    h[4] = Q8_VERSION; h[5] = type; h[6] = 0; h[7] = 0;
    wr32(h + 8, id); wr32(h + 12, size);
    if (size) std::memcpy(out + 16, payload, size);
    uint32_t crc = crc_update(0xffffffffU, out + 4, 12 + size) ^ 0xffffffffU;
    wr32(out + 16 + size, crc);
    return 20u + size;
}

static uint32_t error_frame(uint8_t *out, uint32_t cap, uint32_t id, uint32_t code, const char *msg) {
    uint8_t buf[120];
    size_t len = std::strlen(msg);
    if (len > sizeof(buf) - 4) len = sizeof(buf) - 4;
    wr32(buf, code); std::memcpy(buf + 4, msg, len);
    return put_frame(out, cap, Q8_ERROR, id, buf, (uint32_t)len + 4);
}

// Same on-wire validation as the deployed dispatcher, before any state change.
static int valid_instruction(const uint8_t *b, unsigned nq) {
    uint32_t w0 = rd32(b), w1 = rd32(b + 4), w2 = rd32(b + 8), w3 = rd32(b + 12);
    unsigned op = w0 & 15U, target = (w0 >> 4) & 15U, control = (w0 >> 8) & 15U;
    if (op < 1 || op > 11 || target >= nq || (w2 >> 12) || w3) return 0;
    if (op == 10 || op == 11) {
        if (control >= nq || target == control) return 0;
    } else if (control != 15) return 0;
    int32_t p0 = (int32_t)((w0 >> 12) | (w1 << 20));
    int32_t p1 = (int32_t)((w1 >> 12) | (w2 << 20));
    if (op >= 7 && op <= 9) {
        if (p0 < -1073741824 || p0 > 1073741824 || p1 < -1073741824 || p1 > 1073741824) return 0;
        int64_t norm = (int64_t)p0 * p0 + (int64_t)p1 * p1;
        int64_t delta = norm - ((int64_t)1 << 60);
        if (delta < -((int64_t)1 << 40) || delta > ((int64_t)1 << 40)) return 0;
    } else if (p0 || p1) return 0;
    return 1;
}

static uint32_t run_circuit(const uint8_t *rx, uint32_t size, uint32_t id, uint8_t *out, uint32_t cap) {
    if (size < 4 || (size - 4) % 16) return error_frame(out, cap, id, 3, "Invalid RUN length.");
    unsigned nq = rd16(rx), basis = rd16(rx + 2), count = (size - 4) / 16;
    if (nq < 1 || nq > 8 || basis >= (1U << nq) || count > Q8_MAX_INST)
        return error_frame(out, cap, id, 3, "Invalid qubits, basis or instruction count.");
    for (unsigned k = 0; k < count; ++k)
        if (!valid_instruction(rx + 4 + 16 * k, nq))
            return error_frame(out, cap, id, 3, "Invalid opcode, operand or rotation coefficients.");
    for (unsigned i = 0; i < NUM_STATES; ++i) g_state[i] = 0;
    g_state[basis] = state_word_t(1073741824ULL);           // 1.0 in Q2.30, imag = 0
    for (unsigned k = 0; k < count; ++k) {
        instruction_word_t w = 0;
        for (int byte = 0; byte < 16; ++byte) w.range(8 * byte + 7, 8 * byte) = rx[4 + 16 * k + byte];
        g_inst[k] = w;
    }
    auto t0 = std::chrono::steady_clock::now();
    int rc = qsim8(g_state, g_inst, (int)count, (int)nq);
    auto t1 = std::chrono::steady_clock::now();
    g_last_core_ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
    if (rc != 0) return error_frame(out, cap, id, 4, "Core rejected the circuit.");
    static uint8_t tx[16 + 256 * 8];
    unsigned amplitudes = 1U << nq;
    wr16(tx, (uint16_t)nq); wr16(tx + 2, (uint16_t)amplitudes);
    wr32(tx + 4, 1000000000U); wr64(tx + 8, g_last_core_ns);   // timer in ns
    for (unsigned i = 0; i < amplitudes; ++i) {
        uint64_t v = g_state[i].to_uint64();
        wr64(tx + 16 + 8 * i, v);                                 // real[31:0], imag[63:32]
    }
    return put_frame(out, cap, Q8_RUN_REPLY, id, tx, 16 + amplitudes * 8);
}

// Process exactly one request frame. Returns 0 and the reply length, or <0 on misuse.
Q8_EXPORT int q8_service(const uint8_t *in, uint32_t in_len, uint8_t *out, uint32_t cap, uint32_t *out_len) {
    *out_len = 0;
    if (in_len < 20 || std::memcmp(in, "Q8PK", 4) != 0) return -1;
    const uint8_t *tail = in + 4;
    uint32_t id = rd32(tail + 4), size = rd32(tail + 8);
    if (tail[0] != Q8_VERSION || rd16(tail + 2) != 0 || size > Q8_MAX_PAYLOAD || in_len != 20 + size) {
        *out_len = error_frame(out, cap, id, 1, "Invalid protocol header."); return 0;
    }
    const uint8_t *payload = in + 16;
    uint32_t crc = crc_update(0xffffffffU, tail, 12);
    crc = crc_update(crc, payload, size) ^ 0xffffffffU;
    if (crc != rd32(in + 16 + size)) { *out_len = error_frame(out, cap, id, 2, "CRC mismatch."); return 0; }
    if (tail[1] == Q8_HELLO && size == 0) {
        uint8_t caps[12];
        wr16(caps, 8); wr16(caps + 2, 20); wr16(caps + 4, Q8_MAX_INST);
        wr16(caps + 6, 16); wr32(caps + 8, Q8_BUILD);
        *out_len = put_frame(out, cap, Q8_HELLO_REPLY, id, caps, 12);
    } else if (tail[1] == Q8_RUN) {
        *out_len = run_circuit(payload, size, id, out, cap);
    } else {
        *out_len = error_frame(out, cap, id, 1, "Unknown command or invalid HELLO length.");
    }
    return *out_len ? 0 : -2;
}

Q8_EXPORT uint64_t q8_last_core_ns(void) { return g_last_core_ns; }
