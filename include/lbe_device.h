#ifndef LBE_DEVICE_H
#define LBE_DEVICE_H

#include <stdint.h>

struct lbe_device;

enum lbe_model {
	LBE_1420 = 0,
	LBE_1421_DUALOUT, // dual output
	LBE_MINI          // Mini Precision GPS Reference Clock (single output, PID 0x2211)
};

struct lbe_status {
    uint8_t raw_status;
    uint32_t frequency1;
    uint32_t frequency2;
    int outputs_enabled;
    int fll_enabled;
    int pll_locked;
    int antenna_ok;
    int pps_enabled;
    int out1_power_low;
    int out2_power_low;
};

struct lbe_device* lbe_open_device(void);
void lbe_close_device(struct lbe_device* dev);
enum lbe_model lbe_get_model(struct lbe_device* dev);
int lbe_get_device_status(struct lbe_device* dev, struct lbe_status* status);
int lbe_set_frequency(struct lbe_device* dev, int output, uint32_t frequency);
int lbe_set_outputs_enable(struct lbe_device* dev, int enable);
int lbe_blink_leds(struct lbe_device* dev);
int lbe_set_frequency_temp(struct lbe_device* dev, int output, uint32_t frequency);
int lbe_set_pll_mode(struct lbe_device* dev, int fll_mode);
int lbe_set_1pps(struct lbe_device* dev, int enable);
int lbe_set_power_level(struct lbe_device* dev, int output, int low_power);
/* Mini-only: set output drive strength directly (0..3 → 8/16/24/32 mA). */
int lbe_mini_set_drive(struct lbe_device* dev, int level);

/* Mini-only: read one UBX-NAV-PVT-bearing INPUT report. On success,
 * fills the uint8_t[64] buffer with the raw 64-byte input report. The
 * caller is responsible for parsing the UBX payload starting at byte
 * offset 2 (where the firmware places `B5 62 ...` when NAV data is
 * available). Returns 0 on success, -1 on error. */
int lbe_mini_read_input(struct lbe_device* dev, uint8_t buf64[64],
                        int timeout_ms);

#endif // LBE_DEVICE_H
