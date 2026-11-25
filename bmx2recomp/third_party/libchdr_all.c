/* All of libchdr (third_party/libchdr: github.com/rtissera/libchdr at 47d794151b2b64f6aba60304e6480f4f5a2bc24b,
 * unchanged except: no CMake files, tests or LZMA assembly; zstd's BSD LICENSE added from facebook/zstd v1.5.7)
 * in one file to compile.
 * Upstream's unity.c leaves out the A/V Huffman codec that libchdr_chd.c still names, so it is added here. */
#include "libchdr/unity.c"
#include "libchdr/src/libchdr_codec_avhuff.c"
