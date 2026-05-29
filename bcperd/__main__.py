from .daemon import Daemon


def main():
    daemon = Daemon()
    daemon.start()


if __name__ == "__main__":
    main()
