OUT := $(JUST_BUILDIT_OUTPUT_DIR)
EXT := $(JUST_BUILDIT_EXT_SUFFIX)
CC_EXT = $(CC) $(JUST_BUILDIT_LDFLAGS) -I$(JUST_BUILDIT_INCLUDE_DIR) $< -o $@ $(JUST_BUILDIT_LIBS)

EXTS := \
	$(OUT)/imagelib/filters/_blur$(EXT) \
	$(OUT)/imagelib/codec/_encode$(EXT)

all: $(EXTS)
	find src/imagelib -name "*.py" | while read f; do \
		dest=$(OUT)/$${f#src/}; \
		mkdir -p $$(dirname $$dest); \
		cp $$f $$dest; \
	done

$(OUT)/imagelib/filters/_blur$(EXT): src/imagelib/filters/_blur.c | $(OUT)/imagelib/filters
	$(CC_EXT)

$(OUT)/imagelib/codec/_encode$(EXT): src/imagelib/codec/_encode.c | $(OUT)/imagelib/codec
	$(CC_EXT)

$(OUT)/imagelib/filters $(OUT)/imagelib/codec:
	mkdir -p $@

clean:
	rm -f src/imagelib/filters/_blur*.so src/imagelib/filters/_blur*.pyd
	rm -f src/imagelib/codec/_encode*.so src/imagelib/codec/_encode*.pyd
