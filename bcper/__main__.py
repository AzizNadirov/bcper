import tkinter  # noqa: F401  -- force early _tkinter / XInitThreads init before threading

from bcper.gui import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
