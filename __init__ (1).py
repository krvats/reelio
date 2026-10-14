def get_target(ttype):
    from . import instagram, youtube
    return {"instagram": instagram, "youtube": youtube}[ttype]
