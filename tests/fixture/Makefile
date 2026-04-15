# Makefile for just-build test fixture.
#
# just-build sets these env vars before calling make:
#   JUST_BUILDIT_NAME          = hello
#   JUST_BUILDIT_INCLUDE_DIR   = /path/to/python/include
#   JUST_BUILDIT_OUTPUT_DIR    = /tmp/just-build-xyz/output
#   JUST_BUILDIT_EXT_SUFFIX    = .cpython-312-x86_64-linux-gnu.so

CC      ?= cc
CFLAGS  ?= -O2 -Wall

SRC     := src/hello/hello.c
TARGET  := $(JUST_BUILDIT_OUTPUT_DIR)/$(JUST_BUILDIT_NAME)$(JUST_BUILDIT_EXT_SUFFIX)

.PHONY: all clean

all: $(TARGET)

$(TARGET):
	$(CC) $(CFLAGS) \
		$(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		$(SRC) \
		-o $(TARGET) \
		$(JUST_BUILDIT_LIBS)

clean:
	rm -f $(TARGET)
