"""Config flow for DTU Proxy."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DtuProxyApi,
    DtuProxyConnectionError,
    DtuProxyInvalidResponse,
    normalize_host,
    validate_proxy_status,
)
from .const import (
    CONF_METER_INTERVAL,
    CONF_PORT,
    DEFAULT_METER_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    METER_INTERVALS,
)


class DtuProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one DTU Proxy installation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate the proxy endpoint."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
                port = user_input[CONF_PORT]
                api = DtuProxyApi(async_get_clientsession(self.hass), host, port)
                status = await api.async_status()
                validate_proxy_status(status)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            except DtuProxyConnectionError:
                errors["base"] = "cannot_connect"
            except DtuProxyInvalidResponse:
                errors["base"] = "invalid_proxy"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the integration options flow."""
        return DtuProxyOptionsFlow()


class DtuProxyOptionsFlow(config_entries.OptionsFlow):
    """Configure the meter update interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure the integration options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_METER_INTERVAL: int(user_input[CONF_METER_INTERVAL])},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_METER_INTERVAL,
                        default=int(
                            self.config_entry.options.get(
                                CONF_METER_INTERVAL, DEFAULT_METER_INTERVAL
                            )
                        ),
                    ): vol.In(METER_INTERVALS)
                }
            ),
        )
