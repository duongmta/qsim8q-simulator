#include "qsim_hls.h"

static const q_real_t INV_SQRT2 = q_real_t(0.70710678118654752440);

// Map pair number i to the basis-state index whose target bit is 0.
static inline int pair_index_zero(int i, int step) {
#pragma HLS INLINE
    return ((i & ~(step - 1)) << 1) | (i & (step - 1));
}

// -----------------------------------------------------------------------------
// V5 single-qubit kernel: OUT-OF-PLACE update.
//
// src is read-only during the gate.
// dst is write-only during the gate.
//
// This removes the V1/V4 read-after-write / port conflict caused by updating
// one BRAM state array in-place. Real+imag are packed in one 64-bit word so one
// memory access transfers one complete complex amplitude.
// -----------------------------------------------------------------------------
static void apply_single_qubit_gate(
    state_word_t src[NUM_STATES],
    state_word_t dst[NUM_STATES],
    int active_states,
    GateType gate,
    uint8_t target,
    q_real_t p0,
    q_real_t p1) {

#pragma HLS INLINE off

    const int step = 1 << target;
    const int pair_count = active_states >> 1;

single_gate_loop:
    for (int i = 0; i < pair_count; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE
#endif
        // For a fixed target, every basis-state index belongs to exactly one pair.
        // Therefore writes from different iterations do not overlap.
#pragma HLS DEPENDENCE variable=dst inter false

        const int idx0 = pair_index_zero(i, step);
        const int idx1 = idx0 | step;

        const state_word_t w0 = src[idx0];
        const state_word_t w1 = src[idx1];

        const q_real_t ar = state_real(w0);
        const q_real_t ai = state_imag(w0);
        const q_real_t br = state_real(w1);
        const q_real_t bi = state_imag(w1);

        q_real_t o0r = ar;
        q_real_t o0i = ai;
        q_real_t o1r = br;
        q_real_t o1i = bi;

        switch (gate) {
        case GATE_X:
            o0r = br;  o0i = bi;
            o1r = ar;  o1i = ai;
            break;

        case GATE_Y:
            // Y[a,b]^T = [-i*b, i*a]^T
            o0r = bi;   o0i = -br;
            o1r = -ai;  o1i = ar;
            break;

        case GATE_Z:
            o1r = -br;
            o1i = -bi;
            break;

        case GATE_H:
            o0r = INV_SQRT2 * (ar + br);
            o0i = INV_SQRT2 * (ai + bi);
            o1r = INV_SQRT2 * (ar - br);
            o1i = INV_SQRT2 * (ai - bi);
            break;

        case GATE_S:
            // diag(1, i)
            o1r = -bi;
            o1i = br;
            break;

        case GATE_T:
            // diag(1, exp(i*pi/4))
            o1r = INV_SQRT2 * (br - bi);
            o1i = INV_SQRT2 * (br + bi);
            break;

        case GATE_RX:
            // p0 = cos(theta/2), p1 = sin(theta/2)
            o0r = p0 * ar + p1 * bi;
            o0i = p0 * ai - p1 * br;
            o1r = p1 * ai + p0 * br;
            o1i = -p1 * ar + p0 * bi;
            break;

        case GATE_RY:
            o0r = p0 * ar - p1 * br;
            o0i = p0 * ai - p1 * bi;
            o1r = p1 * ar + p0 * br;
            o1i = p1 * ai + p0 * bi;
            break;

        case GATE_RZ:
            o0r = p0 * ar + p1 * ai;
            o0i = p0 * ai - p1 * ar;
            o1r = p0 * br - p1 * bi;
            o1i = p1 * br + p0 * bi;
            break;

        default:
            // Unknown 1Q opcode: preserve the pair.
            break;
        }

        dst[idx0] = pack_state(o0r, o0i);
        dst[idx1] = pack_state(o1r, o1i);
    }
}

// -----------------------------------------------------------------------------
// V5 controlled 2-qubit kernel: also OUT-OF-PLACE.
//
// Unlike the old in-place implementation, iterations whose control bit is 0
// must explicitly copy src -> dst because dst is a different memory buffer.
// -----------------------------------------------------------------------------
static void apply_two_qubit_gate(
    state_word_t src[NUM_STATES],
    state_word_t dst[NUM_STATES],
    int active_states,
    GateType gate,
    uint8_t control,
    uint8_t target) {

#pragma HLS INLINE off

    const int step = 1 << target;
    const int control_mask = 1 << control;
    const int pair_count = active_states >> 1;

controlled_gate_loop:
    for (int i = 0; i < pair_count; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE
#endif
#pragma HLS DEPENDENCE variable=dst inter false

        const int idx0 = pair_index_zero(i, step);
        const int idx1 = idx0 | step;

        const state_word_t w0 = src[idx0];
        const state_word_t w1 = src[idx1];

        if ((idx0 & control_mask) == 0) {
            // Gate is inactive for this pair: copy it unchanged.
            dst[idx0] = w0;
            dst[idx1] = w1;
        } else if (gate == GATE_CNOT) {
            // Target flip swaps the amplitudes of the target-0/target-1 pair.
            dst[idx0] = w1;
            dst[idx1] = w0;
        } else { // GATE_CZ
            const q_real_t br = state_real(w1);
            const q_real_t bi = state_imag(w1);
            dst[idx0] = w0;
            dst[idx1] = pack_state(-br, -bi);
        }
    }
}

void quantum_simulator(
    state_word_t state_vector[NUM_STATES],
    instruction_word_t instructions[MAX_INSTRUCTIONS],
    int num_inst,
    int num_qubits) {

#pragma HLS INTERFACE m_axi port=state_vector offset=slave bundle=gmem_state depth=NUM_STATES max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE m_axi port=instructions offset=slave bundle=gmem_inst depth=MAX_INSTRUCTIONS max_read_burst_length=16
#pragma HLS INTERFACE s_axilite port=state_vector bundle=ctrl
#pragma HLS INTERFACE s_axilite port=instructions bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_inst bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_qubits bundle=ctrl
#pragma HLS INTERFACE s_axilite port=return bundle=ctrl

    // V5 memory experiment:
    // Two full complex state buffers are kept on-chip. Each is 256 x 64 bits
    // at the normalized 8-qubit maximum. Gates alternate A->B, B->A (ping-pong).
    state_word_t state_a[NUM_STATES];
    state_word_t state_b[NUM_STATES];

#pragma HLS BIND_STORAGE variable=state_a type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=state_b type=ram_t2p impl=bram

    int nq = num_qubits;
    if (nq < 1) {
        nq = 1;
    } else if (nq > MAX_QUBITS) {
        nq = MAX_QUBITS;
    }
    const int active_states = 1 << nq;

    // Initial state always enters buffer A.
load_state:
    for (int i = 0; i < active_states; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE
#endif
        state_a[i] = state_vector[i];
    }

    int instruction_count = num_inst;
    if (instruction_count < 0) {
        instruction_count = 0;
    } else if (instruction_count > MAX_INSTRUCTIONS) {
        instruction_count = MAX_INSTRUCTIONS;
    }

    // false => current valid state is in A
    // true  => current valid state is in B
    bool current_is_b = false;

execute_inst:
    for (int k = 0; k < instruction_count; ++k) {
        const instruction_word_t word = instructions[k];
        const GateType gate = instruction_gate(word);
        const uint8_t target = instruction_target(word);
        const uint8_t control = instruction_control(word);

        // Ignore identity and malformed target instructions without swapping
        // ping-pong ownership, because no destination buffer is written.
        if (gate == GATE_I || target >= nq) {
            continue;
        }

        bool execute_gate = true;

        if (gate == GATE_CNOT || gate == GATE_CZ) {
            if (control >= nq || control == target) {
                execute_gate = false;
            }

            if (execute_gate) {
                if (!current_is_b) {
                    apply_two_qubit_gate(state_a, state_b, active_states,
                                         gate, control, target);
                } else {
                    apply_two_qubit_gate(state_b, state_a, active_states,
                                         gate, control, target);
                }
            }
        } else {
            if (!current_is_b) {
                apply_single_qubit_gate(state_a, state_b, active_states,
                                        gate, target,
                                        instruction_param0(word),
                                        instruction_param1(word));
            } else {
                apply_single_qubit_gate(state_b, state_a, active_states,
                                        gate, target,
                                        instruction_param0(word),
                                        instruction_param1(word));
            }
        }

        if (execute_gate) {
            current_is_b = !current_is_b;
        }
    }

    // Return whichever ping-pong buffer contains the final state.
store_state:
    for (int i = 0; i < active_states; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE
#endif
        state_vector[i] = current_is_b ? state_b[i] : state_a[i];
    }
}


