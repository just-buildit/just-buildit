# Windows: clang-cl against native CPython (the MSVC ABI). Run it from an
# environment where clang-cl can find the MSVC toolchain (a Developer
# Command Prompt, or scripts/msvc-env.sh on a CI runner).
#
# make's built-in CC is `cc`, which is not on a Windows PATH; an environment
# CC still wins, so only the built-in default is replaced.
ifeq ($(origin CC),default)
CC := clang-cl
endif

TARGET := $(JUST_BUILDIT_OUTPUT_DIR)/add$(JUST_BUILDIT_EXT_SUFFIX)
OBJDIR := build

all: $(TARGET)

# clang-cl takes MSVC's spellings: /LD builds a DLL (JUST_BUILDIT_LDFLAGS),
# /Fe: names the output and /Fo the object directory. JUST_BUILDIT_LIBS is
# the path to python3X.lib; it is an ordinary input file, so it goes after
# the sources. /LD also writes add*.lib and add*.exp beside the output;
# just-buildit removes those before packaging, so they need no handling here.
$(TARGET):
	mkdir -p $(OBJDIR)
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/add/add.c \
		/Fo$(OBJDIR)/ \
		/Fe:$(TARGET) \
		$(JUST_BUILDIT_LIBS)

clean:
	rm -rf $(OBJDIR) src/add/add*.pyd
