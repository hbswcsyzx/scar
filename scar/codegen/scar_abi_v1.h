#ifndef SCAR_ABI_V1_H
#define SCAR_ABI_V1_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Bounds cover the live backing allocation, with upper_bound exclusive.
 * data points to logical element [0, 0]; strides are signed byte offsets.
 * A caller retains every allocation until run returns. Empty arrays may have
 * a null data pointer. Descriptors themselves must point to valid storage. */
typedef struct scar_array_v1 {
    void *data;
    int64_t rank;
    int64_t shape[2];
    int64_t strides[2];
    uintptr_t lower_bound;
    uintptr_t upper_bound;
} scar_array_v1;

enum scar_status_v1 {
    SCAR_OK_V1 = 0,
    SCAR_ARGUMENT_GUARD_V1 = 1,
    SCAR_SHAPE_GUARD_V1 = 2,
    SCAR_FLOATING_GUARD_V1 = 3
};

typedef int32_t (*scar_run_fn_v1)(const scar_array_v1 *inputs,
                                 uint64_t input_count,
                                 scar_array_v1 *output);

typedef struct scar_operator_table_v1 {
    uint32_t abi_version;
    uint32_t struct_size;
    uint64_t input_count;
    scar_run_fn_v1 run;
    const char *plan_sha256;
} scar_operator_table_v1;

#if defined(__GNUC__)
#define SCAR_EXPORT_V1 __attribute__((visibility("default")))
#else
#define SCAR_EXPORT_V1
#endif

SCAR_EXPORT_V1 const scar_operator_table_v1 *scar_get_operator_table_v1(void);

#ifdef __cplusplus
}
#endif
#endif
