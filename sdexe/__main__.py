"""`sdexe` and `python -m sdexe`."""
import sys

# The file commands. They need none of the web app (Flask and every route),
# and loading it took longer than most of them take to run.
FILE_COMMANDS = ("pdf", "image", "audio", "video", "convert", "file")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in FILE_COMMANDS:
        # The one thing the web app's import does that the tools rely on:
        # reading HEIC, for commands that open an image themselves.
        from sdexe import tools_images2  # noqa: F401
        from sdexe.cli_tools import tools_main
        sys.exit(tools_main(sys.argv[1:]))
    from sdexe.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
