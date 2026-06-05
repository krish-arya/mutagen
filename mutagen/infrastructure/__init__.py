"""Infrastructure layer.

Concrete adapters that implement the abstract ports declared in
:mod:`mutagen.core.interfaces`. This is the only layer permitted to perform
real I/O, talk to external processes, or depend on third-party libraries.
"""
