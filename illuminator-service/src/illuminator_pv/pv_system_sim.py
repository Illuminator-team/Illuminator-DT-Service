from pandas import DatetimeIndex, Series
from pvlib.irradiance import get_total_irradiance, erbs
from pvlib.pvarray import pvefficiency_adr
from pvlib.solarposition import get_solarposition
from pvlib.temperature import faiman
from typing import Tuple

class PVSystemSim:

    def __init__(
            self,
            config: dict
        ) -> None:
        """
        Constructor from config.
        """
        # Desired array output in W.
        self.p_stc = config.get('p_stc', 5000.)

        # Irradiance level in W/m2 needed to achieve nominal output.
        self.g_stc = config.get('g_stc', 1000.)

        # ADR model parameters.
        self.k_a = config.get('k_a', 0.99924)
        self.k_d = config.get('k_d',-5.49097)
        self.tc_d = config.get('tc_d', 0.01918)
        self.k_rs = config.get('k_rs', 0.06999)
        self.k_rsh = config.get('k_rsh', 0.2614)

    def simulate_power_output(
            self,
            observation_time: DatetimeIndex,
            air_pressure: Series,
            air_temperature: Series,
            wind_speed: Series,
            global_horizontal_irradiation: Series,
            latitude: float,
            longitude: float,
        ) -> Tuple[Series, Series, Series]:
        """
        Calculate PV system power output (in W), total in-plane irradiance (W/m^2), and PV module efficiency based on weather forecast data.
        """
        # Calculate solar positions.
        solpos = get_solarposition(
            observation_time, latitude=latitude, longitude=longitude,
            pressure=air_pressure, temperature=air_temperature
        )

        # Estimate direct normal irradiation and diffuse horizontal irradiation from global horizontal irradiation.
        estimated_irradiance = erbs(
            global_horizontal_irradiation, solpos.zenith, observation_time
        )

        # Determine total in-plane irradiance and its beam, sky diffuse and ground reflected components.
        total_irrad = get_total_irradiance(
            surface_tilt=latitude, surface_azimuth=180,
            solar_zenith=solpos.apparent_zenith, solar_azimuth=solpos.azimuth,
            dni=estimated_irradiance.dni, ghi=global_horizontal_irradiation, dhi=estimated_irradiance.dhi
        )

        # Calculate PV module temperature using the Faiman model.
        temp_pv = faiman(
            total_irrad.poa_global, air_temperature, wind_speed
        )

        # Calculate PV module efficiency using the ADR model.
        eta_rel = pvefficiency_adr(
            total_irrad.poa_global, temp_pv,
            k_a=self.k_a, k_d=self.k_d, tc_d=self.tc_d, k_rs=self.k_rs, k_rsh=self.k_rsh
        )

        # Calculate PV power output.
        p_mp = self.p_stc * eta_rel * (total_irrad.poa_global / self.g_stc)

        return p_mp, total_irrad.poa_global, eta_rel
