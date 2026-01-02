/*
 * Updated SHA-256 implementation
 * Based on reputable open source implementations for C++11
 */
#include "sha256.hpp"
#include <vector>
#include <iomanip>
#include <sstream>
#include <cstring>

// internal rotation helpers
inline uint32_t right_rot(uint32_t value, unsigned int count) {
    return value >> count | value << (32 - count);
}

void sha256_transform(uint32_t* state, const uint8_t* data) {
    uint32_t data32[64];
    for (int i = 0, j = 0; i < 16; i++, j += 4) {
        data32[i] = (data[j] << 24) | (data[j + 1] << 16) | (data[j + 2] << 8) | (data[j + 3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = right_rot(data32[i - 15], 7) ^ right_rot(data32[i - 15], 18) ^ (data32[i - 15] >> 3);
        uint32_t s1 = right_rot(data32[i - 2], 17) ^ right_rot(data32[i - 2], 19) ^ (data32[i - 2] >> 10);
        data32[i] = data32[i - 16] + s0 + data32[i - 7] + s1;
    }

    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    uint32_t e = state[4], f = state[5], g = state[6], h = state[7];

    static const uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    };

    for (int i = 0; i < 64; i++) {
        uint32_t s1 = right_rot(e, 6) ^ right_rot(e, 11) ^ right_rot(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t temp1 = h + s1 + ch + k[i] + data32[i];
        uint32_t s0 = right_rot(a, 2) ^ right_rot(a, 13) ^ right_rot(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temp2 = s0 + maj;

        h = g; g = f; f = e; e = d + temp1;
        d = c; c = b; b = a; a = temp1 + temp2;
    }

    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

std::string sha256(const std::string& input) {
    uint32_t state[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };

    std::vector<uint8_t> buffer(input.begin(), input.end());
    uint64_t bit_len = buffer.size() * 8;
    
    // Padding
    buffer.push_back(0x80);
    while ((buffer.size() * 8) % 512 != 448) {
        buffer.push_back(0x00);
    }

    for (int i = 7; i >= 0; i--) {
        buffer.push_back((bit_len >> (i * 8)) & 0xff);
    }

    for (size_t i = 0; i < buffer.size(); i += 64) {
        sha256_transform(state, &buffer[i]);
    }

    std::stringstream ss;
    ss << std::hex << std::setfill('0');
    for (int i = 0; i < 8; i++) {
        ss << std::setw(8) << state[i];
    }
    return ss.str();
}
