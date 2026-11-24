"""Single diary setup and optional entity exposure."""

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class VitalityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Vitality", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Optional("expose_scores", default=False): bool}
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return VitalityOptions()


class VitalityOptions(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        default = self.config_entry.options.get(
            "expose_scores", self.config_entry.data.get("expose_scores", False)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional("expose_scores", default=default): bool}
            ),
        )
