"""Vitality Home Assistant entry points."""


async def async_setup(hass, config):
    from .api import register

    register(hass)
    return True


async def async_setup_entry(hass, entry):
    from .runtime import setup_entry

    return await setup_entry(hass, entry)


async def async_unload_entry(hass, entry):
    from .runtime import unload_entry

    return await unload_entry(hass, entry)
