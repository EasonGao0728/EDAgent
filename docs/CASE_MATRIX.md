# Case coverage

Each row identifies a design and its original process. Cell counts are catalog values before any documented tie-cell normalization. The profile column describes the production workbench. The last column describes this qualification campaign on the research worker. [Evidence definitions and process-library sources](QUALIFICATION.md)

| Design | PDK | Standard cells | Hard macros | Workbench profile | Latest qualification evidence |
|---|---|---:|---:|---|---|
| sky130_gcd | Sky130 | 639 | 0 | Placement DEF | Existing profile; original results retained |
| ibench_gcd_legacy | Sky130 | 255 | 0 | Full back end | Existing profile; original results retained |
| sky130_sram_pair | Sky130 | 64 | 2 | Placement DEF | Existing profile; original results retained |
| aes_sky130_t | Sky130 | 9,434 | 0 | Full back end | Existing profile; original results retained |
| aes_legacy | Sky130 | 18,646 | 0 | Full back end | Existing profile; original results retained |
| aes_core_sky130_t | Sky130 | 20,092 | 0 | Full back end | Existing profile; original results retained |
| swerv_nangate45 | Nangate45 | 6,777 | 3 | Full back end | Existing profile; original results retained |
| bp_quad | nangate45 | 1,235,389 | 220 | Input audit | Declared inputs located |
| ariane136 | nangate45 | 174,893 | 136 | Input audit | Native import failed (exit 139) |
| ariane133 | nangate45 | 168,949 | 132 | Input audit | Native import failed (exit 139) |
| bp_multi | nangate45 | 70,634 | 26 | Input audit | Native import DEF, 92,108 nets |
| bp | nangate45 | 120,146 | 24 | Input audit | Native import DEF, 154,082 nets |
| bp_fe | nangate45 | 24,562 | 11 | Input audit | Native import DEF, 31,478 nets |
| bp_be | nangate45 | 42,264 | 10 | Input audit | Native import DEF, 54,103 nets |
| bp_quad_sky130 | sky130 | 968,158 | 220 | Input audit | Declared inputs located |
| ariane136_sky130 | sky130 | 144,748 | 136 | Input audit | Native import DEF, 151,748 nets |
| ariane133_sky130 | sky130 | 137,631 | 44 | Input audit | Native import DEF, 142,800 nets |
| bp_multi_sky130 | sky130 | 75,503 | 26 | Input audit | Native import DEF, 82,041 nets |
| bp_sky130 | sky130 | 120,398 | 24 | Input audit | Native import DEF, 128,002 nets |
| bp_fe_sky130 | sky130 | 20,782 | 11 | Input audit | Native import DEF, 23,383 nets |
| bp_be_sky130 | sky130 | 38,662 | 10 | Input audit | Native import DEF, 42,122 nets |
| bp_quad_asap7 | asap7 | 1,151,155 | 220 | Input audit | Native import DEF, 1,169,700 nets |
| ariane136_asap7 | asap7 | 172,355 | 136 | Input audit | Native import DEF, 177,828 nets |
| ariane133_asap7 | asap7 | 167,348 | 44 | Input audit | Native import DEF, 170,987 nets |
| bp_multi_asap7 | asap7 | 91,504 | 26 | Input audit | Native import DEF, 95,394 nets |
| bp_asap7 | asap7 | 143,047 | 24 | Input audit | Native import DEF, 148,327 nets |
| bp_fe_asap7 | asap7 | 25,084 | 11 | Input audit | Native import DEF, 27,612 nets |
| bp_be_asap7 | asap7 | 48,102 | 10 | Input audit | Native import DEF, 51,150 nets |
| bp_quad_ics55 | ics55 | 925,018 | 220 | Input audit | Waiting for matching ICS55 libraries |
| ariane136_ics55 | ics55 | 137,146 | 136 | Input audit | Waiting for matching ICS55 libraries |
| ariane133_ics55 | ics55 | 130,681 | 44 | Input audit | Waiting for matching ICS55 libraries |
| bp_multi_ics55 | ics55 | 73,181 | 26 | Input audit | Waiting for matching ICS55 libraries |
| bp_ics55 | ics55 | 114,374 | 24 | Input audit | Waiting for matching ICS55 libraries |
| bp_fe_ics55 | ics55 | 20,576 | 11 | Input audit | Waiting for matching ICS55 libraries |
| bp_be_ics55 | ics55 | 37,374 | 10 | Input audit | Waiting for matching ICS55 libraries |
| tinyram | nangate45 | 2,983 | 2 | Input audit | Native import DEF, 3,155 nets |
| jpeg | nangate45 | 59,596 | 0 | Input audit | Native import DEF, 65,791 nets |
| toygpu | nangate45 | 363,570 | 0 | Input audit | Native import DEF, 470,482 nets |
| vortex | nangate45 | 1,771,888 | 0 | Input audit | Native import failed (exit 134) |
| WUKONG | nangate45 | 2,002,273 | 0 | Input audit | Native import failed (exit 134) |
| osip_uart | nangate45 | 6,124 | 0 | Input audit | Native import DEF, 7,461 nets |
| osip_gpio | nangate45 | 980 | 0 | Input audit | Native import DEF, 1,411 nets |
| osip_timer | nangate45 | 636 | 0 | Input audit | Native import DEF, 835 nets |
| osip_i2c | nangate45 | 656 | 0 | Input audit | Native import DEF, 902 nets |
| apb4_rng_nangate45_t | nangate45 | 110 | 0 | Input audit | Native import DEF, 255 nets |
| s35932_nangate45_t | nangate45 | 5,247 | 0 | Input audit | Native import DEF, 7,011 nets |
| s5378_nangate45_t | nangate45 | 752 | 0 | Input audit | Native import DEF, 978 nets |
| s9234_nangate45_t | nangate45 | 638 | 0 | Input audit | Native import DEF, 814 nets |
| salsa20_nangate45_t | nangate45 | 20,335 | 0 | Input audit | Native import DEF, 24,108 nets |
| picorv32_nangate45_t | nangate45 | 7,745 | 0 | Input audit | Native import DEF, 9,532 nets |
