EXT := $(JUST_BUILD_OUTPUT_DIR)/calc/_core$(JUST_BUILD_EXT_SUFFIX)

all: $(EXT)
	cp src/calc/__init__.py $(JUST_BUILD_OUTPUT_DIR)/calc/

$(EXT):
	mkdir -p $(JUST_BUILD_OUTPUT_DIR)/calc
	$(CC) $(JUST_BUILD_LDFLAGS) \
		-I$(JUST_BUILD_INCLUDE_DIR) \
		src/calc/_core.c \
		-o $(EXT) \
		$(JUST_BUILD_LIBS)

clean:
	rm -f src/calc/_core*.so src/calc/_core*.pyd
