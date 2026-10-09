"""Schema-driven translation between the knowledge library and documents of any installed schema.

    knowledge facts ──records──► binding (proposed from the schema model, editable) ──► document markup
    document markup ──binding──► records ──► knowledge facts

Nothing here is written per standard: where a field lives in a document type is read from the installed
schema's model (XSD, DTD or SGML DTD alike) and kept as a reviewable binding.
"""
