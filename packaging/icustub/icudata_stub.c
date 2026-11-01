/* Minimal replacement for Qt's bundled libicudata.so.73 (31 MB).
 * Same layout as ICU's own "stubdata" library: a common-data header with an
 * empty table of contents. Qt falls back to its built-in Unicode tables, and
 * ICU's core character properties are compiled into libicuuc itself. */
#include <stdint.h>

typedef struct {
    uint16_t size;
    uint16_t reservedWord;
    uint8_t isBigEndian, charsetFamily, sizeofUChar, reservedByte;
    uint8_t dataFormat[4];
    uint8_t formatVersion[4];
    uint8_t dataVersion[4];
} UDataInfo;

typedef struct { const char *entryName; const void *pData; } TocEntry;

typedef struct {
    uint16_t headerSize;
    uint8_t magic1, magic2;
    UDataInfo info;
    char padding[8];
    uint32_t count, reserved;
    TocEntry toc[1];
} ICU_Data_Header;

__attribute__((visibility("default")))
const ICU_Data_Header icudt73_dat = {
    32, 0xda, 0x27,
    { sizeof(UDataInfo), 0, 0 /* little endian */, 0 /* ASCII */, 2, 0,
      {0x54, 0x6f, 0x43, 0x50} /* "ToCP" */, {1, 0, 0, 0}, {0, 0, 0, 0} },
    {0, 0, 0, 0, 0, 0, 0, 0},
    0, 0,
    { {0, 0} }
};
