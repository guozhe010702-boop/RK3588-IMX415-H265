# EVM3588-B: build the two H.265 learning programs against the board's
# librockchip-mpp-dev 1.5.0 headers and librockchip_mpp.so.
# Run on the board: make
CROSS ?=
CC := $(CROSS)gcc
MPP_INC ?= /usr/include/rockchip
CPPFLAGS += -I$(MPP_INC)
CFLAGS ?= -O2 -std=gnu11 -Wall -Wextra
LDLIBS += -lrockchip_mpp

all: yuv_mpp_enc v4l2_mpp_enc

mpp_h265.o: mpp_h265.c mpp_h265.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ mpp_h265.c

yuv_mpp_enc.o: yuv_mpp_enc.c mpp_h265.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ yuv_mpp_enc.c

v4l2_mpp_enc.o: v4l2_mpp_enc.c mpp_h265.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ v4l2_mpp_enc.c

yuv_mpp_enc: yuv_mpp_enc.o mpp_h265.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)

v4l2_mpp_enc: v4l2_mpp_enc.o mpp_h265.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)

clean:
	rm -f yuv_mpp_enc v4l2_mpp_enc *.o

.PHONY: all clean
