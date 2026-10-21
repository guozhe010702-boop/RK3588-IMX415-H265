#include "output.hpp"
#include <csignal>
#include <fcntl.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    signal(SIGPIPE, SIG_IGN);
    int fd = open(argv[1], O_CREAT | O_TRUNC | O_WRONLY | O_NONBLOCK, 0600);
    if (fd < 0)
        return 3;
    std::atomic<bool> running{true};
    try {
        {
            yw::Nut nut(fd, 64, 64, 60, running);
            std::vector<uint8_t> frame(64 * 64 * 3 / 2, 128);
            for (auto pts : {0, 100000, 260000, 300000, 650000})
                nut.write(frame.data(), frame.size(), pts);
        }
        close(fd);
        return 0;
    } catch (...) {
        close(fd);
        return 1;
    }
}
