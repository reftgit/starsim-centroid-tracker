CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -std=c11 -Iinclude
LDFLAGS = -lm -lpthread

# SDL2 (canli pencere icin). Kurulum: sudo apt install libsdl2-dev
SDL_CFLAGS = $(shell pkg-config --cflags sdl2)
SDL_LIBS   = $(shell pkg-config --libs sdl2)

SRC_DIR   = src
BUILD_DIR = build

# tracker'a giren kaynaklar (gen_frames.c HARIC -- onun kendi main'i var)
SRCS = queue.c frame_source.c preprocess.c detector.c \
       centroid.c csv_logger.c pipeline.c display.c main.c
OBJS = $(addprefix $(BUILD_DIR)/, $(SRCS:.c=.o))

all: tracker gen_frames

tracker: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDFLAGS) $(SDL_LIBS)

# her .c -> build/ icine .o (SDL cflags hepsine zarar vermez)
$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -c $< -o $@

gen_frames: $(SRC_DIR)/gen_frames.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR) tracker gen_frames

.PHONY: all clean
