"""Enables `python -m apiping`."""
import sys

if __package__:
    from .apiping import main
else:
    from apiping import main

if __name__ == "__main__":
    sys.exit(main())
