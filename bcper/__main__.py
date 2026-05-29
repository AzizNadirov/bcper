import sys

# Pre-initialize Tcl to avoid XCB threading crashes on some Linux systems
if sys.platform.startswith("linux"):
    try:
        import tkinter
        tkinter.Tcl().eval("package require Tk")
    except Exception:
        pass

from bcper.gui import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
