#ifndef QSIM8_CPU_PROFILE_QSIM_CPU_HPP
#define QSIM8_CPU_PROFILE_QSIM_CPU_HPP

#include <complex>
#include <cstdint>
#include <string>
#include <vector>

namespace qsim8_cpu {

using Amplitude = std::complex<float>;

enum class GateType : std::uint8_t {
    H, X, Y, Z, S, T, RX, RY, RZ, CNOT, CZ
};

struct Gate {
    GateType type;
    int target;
    int control;
    float theta;
    float p0;
    float p1;
};

struct Circuit {
    std::string id;
    std::string suite;
    int num_qubits;
    int depth;
    std::vector<Gate> gates;
    std::vector<std::complex<double>> expected;
};

Gate make_gate(GateType type, int target, int control = -1,
               float theta = 0.0f);
GateType gate_from_name(const std::string& name);
const char* gate_name(GateType type);
bool is_two_qubit(GateType type);

void reset_zero_state(std::vector<Amplitude>& state);
void copy_state(const std::vector<Amplitude>& source,
                std::vector<Amplitude>& destination);
void make_dense_state(std::vector<Amplitude>& state);
void apply_single_qubit_gate(std::vector<Amplitude>& state, const Gate& gate);
void apply_two_qubit_gate(std::vector<Amplitude>& state, const Gate& gate);
void execute_circuit(std::vector<Amplitude>& state,
                     const std::vector<Gate>& gates);
std::uint64_t dispatch_checksum(const std::vector<Gate>& gates);
double state_checksum(const std::vector<Amplitude>& state);

}  // namespace qsim8_cpu

#endif
