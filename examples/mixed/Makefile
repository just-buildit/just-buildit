EXT := $(JUST_BUILDIT_OUTPUT_DIR)/calc/_core$(JUST_BUILDIT_EXT_SUFFIX)

all: $(EXT)
	cp src/calc/__init__.py $(JUST_BUILDIT_OUTPUT_DIR)/calc/

$(EXT):
	mkdir -p $(JUST_BUILDIT_OUTPUT_DIR)/calc
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/calc/_core.c \
		-o $(EXT) \
		$(JUST_BUILDIT_LIBS)

clean:
	rm -f src/calc/_core*.so src/calc/_core*.pyd
