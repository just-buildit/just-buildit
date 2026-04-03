# Makefile for just-build test fixture.
#
# just-build sets these env vars before calling make:
#   JUST_BUILD_NAME          = hello
#   JUST_BUILD_INCLUDE_DIR   = /path/to/python/include
#   JUST_BUILD_OUTPUT_DIR    = /tmp/just-build-xyz/output
#   JUST_BUILD_EXT_SUFFIX    = .cpython-312-x86_64-linux-gnu.so

CC      ?= cc
CFLAGS  ?= -O2 -Wall

SRC     := src/hello/hello.c
TARGET  := $(JUST_BUILD_OUTPUT_DIR)/$(JUST_BUILD_NAME)$(JUST_BUILD_EXT_SUFFIX)

.PHONY: all clean

all: $(TARGET)

$(TARGET):
	$(CC) $(CFLAGS) \
		$(JUST_BUILD_LDFLAGS) \
		-I$(JUST_BUILD_INCLUDE_DIR) \
		$(SRC) \
		-o $(TARGET) \
		$(JUST_BUILD_LIBS)

clean:
	rm -f $(TARGET)
