# process_ambience_data.py

# Classes and methods for processing the AmBIENCe datasets.

import pandas as pd
import numpy as np
from . import __version__
from itertools import product
from frictionless import Package
from datetime import datetime


class AmBIENCeDataset:
    """An object class for containing and processing the raw AmBIENCe data."""

    def __init__(
        self,
        building_stock_properties_path="data_sources/ambience/AmBIENCe_Deliverable-4.1_Database-of-greybox-model-parameter-values.xlsx",
        building_stock_heatsys_path="data_sources/ambience/AmBIENCe-WP4-T4.2-Buildings_Energy_systems_Database_EU271.xlsx",
        structure_types_path="data_assumptions/structure_types.csv",
        building_type_mappings_path="data_assumptions/building_type_mappings.csv",
        shapefile_mappings_path="data_assumptions/shapefile_mappings.csv",
        fenestration_path="data_assumptions/fenestration.csv",
        ventilation_path="data_assumptions/ventilation.csv",
        building_stock_year=2016,
        interior_node_depth=0.1,
        period_of_variations=1209600,
        heatsys_skiprows=[0],
    ):
        """
        Read the AmBIENCe project raw data and assumptions.

        Parameters
        ----------
        building_stock_properties_path : str
            path to the 'AmBIENCe_Deliverable-4.1_Database-of-greybox-model-parameter-values.xlsx' raw data file.
        building_stock_heatsys_path : str
            path to the 'AmBIENCe-WP4-T4.2-Buildings_Energy_systems_Database_EU271.xlsx' raw data file.
        structure_types_path : str
            path to the 'structure_types.csv' containing assumptions regarding the properties of different structure types.
        building_type_mappings_path : str
            path to the `building_type_mappings.csv` containing building type to building stock mappings.
        shapefile_mappings_path : str
            path to the `shapefile_mappings.csv` mapping country codes to their corresponding shapefiles.
        fenestration_path : str
            path to the `fenestration.csv` containing assumption regarding fenestration properties.
        ventilation_path : str
            path to the `ventilation.csv` containing assumptions regarding ventilation properties.
        building_stock_year : int
            year the building stock data represents, 2016 by default based on the AmBIENCe data.
        interior_node_depth : float
            assumed depth of the aggregated effective thermal mass within the structures, given as a fraction of the total thermal resistance from the indoor surface to the middle of the thermal insulation.
        period_of_variations : float
            assumed period of variations in seconds for the 'EN ISO 13786:2017 Annex C.2.4 Effective thickness method'.
        heatsys_skiprows : array
            row indices to skip when reading AmBIENCe heating system data.
        """
        self.structure_types = pd.read_csv(structure_types_path).set_index(
            "structure_type"
        )
        self.building_type_mappings = pd.read_csv(
            building_type_mappings_path
        ).set_index("building_type")
        self.shapefile_mappings = pd.read_csv(shapefile_mappings_path).set_index(
            "country"
        )
        self.interior_node_depth = interior_node_depth
        self.period_of_variations = period_of_variations
        self.fenestration = pd.read_csv(fenestration_path).set_index(
            [
                "REFERENCE BUILDING WINDOW GLAZING TYPE",
                "REFERENCE BUILDING WINDOW COATED",
            ]
        )
        self.ventilation = pd.read_csv(ventilation_path)
        self.data = self.preprocess_data(
            building_stock_properties_path,
            building_stock_heatsys_path,
            building_stock_year,
            heatsys_skiprows,
        )

    def preprocess_data(
        self,
        building_stock_properties_path,
        building_stock_heatsys_path,
        building_stock_year,
        heatsys_skiprows,
    ):
        """
        Preprocess AmBIENCe data to make it more manageable.

        Parameters
        ----------
        building_stock_properties_path : str
            path to the 'AmBIENCe_Deliverable-4.1_Database-of-greybox-model-parameter-values.xlsx' raw data file.
        building_stock_heatsys_path : str
            path to the 'AmBIENCe-WP4-T4.2-Buildings_Energy_systems_Database_EU271.xlsx' raw data file.
        building_stock_year : int
            year the building stock data represents.
        heatsys_skiprows : array
            row indices to skip when reading AmBIENCe heating system data.

        Returns
        -------
        data
            a DataFrame containing the combined and extended AmBIENCe data.
        """
        data = pd.merge(  # Merge the data together to make it easier to deal with.
            pd.read_excel(building_stock_properties_path),
            pd.read_excel(
                building_stock_heatsys_path, skiprows=heatsys_skiprows
            ),  # Skip first row of header, later headers will be omitted through inner join.
            left_on="REFERENCE BUILDING CODE",
            right_on="Building typology",
        )
        # Rename columns for convenience later on
        data = data.rename(
            columns={
                "REFERENCE BUILDING USE CODE": "building_type",
                "REFERENCE BUILDING COUNTRY CODE": "location_id",
                "NUMBER OF REFERENCE BUILDINGS IN THE BUILDING STOCK SEGMENT": "number_of_buildings",
                "REFERENCE BUILDING USEFUL FLOOR AREA (m2)": "average_gross_floor_area_m2_per_building",
            }
        )
        # Normalize heating system prevalency to avoid distorting the statistics just to be sure (there was a bug in the raw data).
        cols = [f"HEATING SYSTEM {i} PREVALENCY ON BUILDING STOCK" for i in (1, 2, 3)]
        tot = data[cols].sum(axis=1)
        for c in cols:
            data[c] = data[c] / tot
        # Include new column for heat source, since district heating is not indicated by "FUEL USED"
        cols1 = [f"HEATING SYSTEM {i} HEAT SOURCE" for i in (1, 2, 3)]
        cols2 = [f"HEATING SYSTEM {i} FUEL USED" for i in (1, 2, 3)]
        cols3 = [f"HEATING SYSTEM {i} DIMENSIONS" for i in (1, 2, 3)]
        for c1, c2, c3 in zip(cols1, cols2, cols3):
            data[c1] = data[c2]
            data.loc[data[c3] == "District", c1] = "District"
        # Create and add `building_period` to avoid dealing with it manually all the time.
        data["building_period"] = data[
            [
                "REFERENCE BUILDING CONSTRUCTION YEAR LOW",
                "REFERENCE BUILDING CONSTRUCTION YEAR HIGH",
            ]
        ].apply(lambda row: "-".join(row.values.astype(str)), axis=1)
        # Calculate structure weights for each row
        col = "average_gross_floor_area_m2_per_building"
        cols = [
            "building_type",
            "building_period",
            "location_id",
        ]
        data = data.set_index(cols)
        agg_data = data.groupby(cols).agg(
            total_area_over_material_combinations_m2=(col, sum)
        )
        data = data.join(agg_data)
        data["material_combination_weight"] = (
            data[col] / data["total_area_over_material_combinations_m2"]
        )
        # Join building type and shapefile mappings for convenience.
        data = data.reset_index()
        data = data.join(self.shapefile_mappings, on="location_id")
        data = data.join(
            self.building_type_mappings,
            on="building_type",
            rsuffix="_building_type",
        )
        # Create `building_stock` label for convenience
        data["building_stock_year"] = building_stock_year
        data["building_stock"] = (
            "AmBIENCe_"
            + data["building_stock_year"].apply(str)
            + "_"
            + data["location_id"]
            + "_"
            + data["category"]
        )
        return data.set_index("REFERENCE BUILDING CODE")

    def extrapolate(self, mappings={}, tag="", year=2016):
        """
        Extrapolate AmBIENCeDataset for new countries.

        Essentially copies, renames, and scales data based on existing values for new countries.
        The `mappings` maps existing countries to new countries, along with a scaling factor
        for the `number_of_buildings` parameter in the `building_stock_statistics`.
        All other parameters are preserved from the origin country data.

        This method doesn't return anything, but instead extends `self.data`.

        Parameters
        ----------
        mappings : dictionary
            Maps data to be cloned from key to value, along with a scaling coefficient for `number_of_buildings`. Default scaling coefficients are based on UN 2024 World Population Prospects.
        tag : str
            A string added to the newly created `building_stock`s to distinguish synthetic data.
        year : int
            Year for the building stock, 2016 by default from AmBIENCe data.
        """
        data_list = [self.data.reset_index()]
        for c1, (c2, coeff) in mappings.items():
            df = self.data.reset_index().drop(
                columns=["shapefile_path", "notes"]
            )  # Remove shapefile mappings and notes
            df = df.loc[df.location_id == c1]  # Filter by country 1
            df["REFERENCE BUILDING CODE"] = df["REFERENCE BUILDING CODE"].str.replace(
                c1, c2
            )  # Rename reference building
            df.location_id = df.location_id.replace(c1, c2)  # Rename country
            df = df.join(
                self.shapefile_mappings, on="location_id"
            )  # Re-join to update shapefile path
            df.building_stock = (
                tag
                + "_"
                + df.building_stock_year.apply(str)
                + "_"
                + df.location_id
                + "_"
                + df.category
            )  # Form new building stock names.
            df.number_of_buildings = (
                df.number_of_buildings * coeff
            )  # Scale number of buildings
            data_list.append(df)
        self.data = pd.concat(data_list).set_index("REFERENCE BUILDING CODE")

    def building_stocks(self, for_processing=False):
        """
        Process required building stocks from the data.

        Note that this function operates only on the AmBIENCe dataset.
        Thus, it will not contain data beyond its scope.

        Parameters
        ----------
        for_processing=False : boolean
            Flag to preserve "REFERENCE BUILDING CODE" indexing.

        Returns
        -------
        building_stocks_df
            a DataFrame for building_stock_csv export.
        """
        return (
            self.data[
                [
                    "building_stock",
                    "building_stock_year",
                    "shapefile_path",
                    "raster_weight_path",
                    "notes",
                ]
            ]
            .drop_duplicates()
            .set_index("building_stock")
        )

    def building_periods(self):
        """
        Process the unique building periods from the data.

        Returns
        -------
        building_periods_df
            a DataFrame for building_period.csv export.
        """
        return (
            self.data[
                [
                    "building_period",
                    "REFERENCE BUILDING CONSTRUCTION YEAR LOW",
                    "REFERENCE BUILDING CONSTRUCTION YEAR HIGH",
                ]
            ]
            .rename(
                columns={
                    "REFERENCE BUILDING CONSTRUCTION YEAR LOW": "period_start",
                    "REFERENCE BUILDING CONSTRUCTION YEAR HIGH": "period_end",
                }
            )
            .set_index("building_period")
            .drop_duplicates()
        )

    def calculate_building_stock_statistics(self):
        """
        Process the basic building stock statistics from data for ArchetypeBuildingModel.jl.

        Returns
        -------
        building_stock_statistics_df
            a DataFrame for building_stock_statistics.csv export.
        """
        # Form the new dataframe
        bss = pd.DataFrame(  # Form the basic structure.
            [
                [
                    r["building_stock"],
                    r["building_type"],
                    r["building_period"],
                    r["location_id"],
                    r[" ".join([hs, "HEAT SOURCE"])],  # Heating system fuel from data.
                    r["number_of_buildings"]
                    * r[
                        " ".join([hs, "PREVALENCY ON BUILDING STOCK"])
                    ],  # Multiply number of buildings by heat source prevalency.
                    r[
                        "average_gross_floor_area_m2_per_building"
                    ],  # Useful floor area estimated to be roughly equivalent to gross-floor area.
                ]
                for ((i, r), hs) in product(
                    self.data.iterrows(),
                    ["HEATING SYSTEM 1", "HEATING SYSTEM 2", "HEATING SYSTEM 3"],
                )
            ],
            columns=[
                "building_stock",
                "building_type",
                "building_period",
                "location_id",
                "heat_source",
                "number_of_buildings",
                "average_gross_floor_area_m2_per_building",
            ],
        )
        return (
            bss.dropna()  # Drop NaN rows with invalid heating system data.
            .groupby(  # Group by the actual dimensions...
                [
                    "building_stock",
                    "building_type",
                    "building_period",
                    "location_id",
                    "heat_source",
                ]
            )
            .agg(  # ... and aggregate over the different structural classes in the raw data.
                {
                    "number_of_buildings": "sum",
                    "average_gross_floor_area_m2_per_building": "mean",
                }
            )
        )

    def calculate_weighted_effective_thermal_mass(
        self,
        r,
        st,
    ):
        """
        Calculate the effective thermal mass according to 'EN ISO 13786:2017 Annex C.2.4 effective thickness method'.

        Note that internal structures assume no insulation.

        Parameters
        ----------
        r : DataFrame
            row of the raw AmBIENCe data used for the calculations.
        st : str
            the ABM structure type currently being processed.

        Returns
        -------
        effective_thermal_mass_J_m2K
        """
        pretext = " ".join(
            ["REFERENCE BUILDING", self.structure_types.loc[st, "mapping"]]
        )
        shc = (
            r[" ".join([pretext, "MATERIAL THICKNESS (m)"])]
            * r[" ".join([pretext, "MATERIAL DENSITY (kg/m3)"])]
            * r[" ".join([pretext, "MATERIAL SPECIFIC HEAT CAPACITY (J/kg/K)"])]
            + (
                not self.structure_types.loc[st, "is_internal"]
            )  # Internal structures assume no insulation.
            * 0.5
            * r[" ".join([pretext, "INSULATION MATERIAL THICKNESS (m)"])]
            * r[" ".join([pretext, "INSULATION MATERIAL DENSITY (kg/m3)"])]
            * r[
                " ".join(
                    [pretext, "INSULATION MATERIAL SPECIFIC HEAT CAPACITY (J/kg/K)"]
                )
            ]
        )
        # Apply the period of variations according to 'EN ISO 13786:2017 Annex C.2.4 effective thickness method'
        return np.sqrt(
            shc**2
            / (
                1
                + (2 * np.pi / self.period_of_variations) ** 2
                * shc**2
                * self.structure_types.loc[st, "interior_resistance_m2K_W"] ** 2
            )
        )

    def calculate_U_values(self, r, st):
        """
        Calculate U-values for structure types.

        Note that internal structures assume no insulation.
        Ground-coupled heat losses based on 'Kissock. K., Simplified Model for Ground Heat Transfer from Slab-on-Grade Buildings, (c) 2013 ASHRAE'

        Parameters
        ----------
        r : DataFrame
            row of the raw AmBIENCe data used for the calculations.
        st : str
            the ABM structure type currently being processed.

        Returns
        -------
        U_values_W_m2K
            a tuple containing the exterior, ground, interior, and total U-values of the structure.
        """
        pretext = " ".join(
            ["REFERENCE BUILDING", self.structure_types.loc[st, "mapping"]]
        )
        material_resistance = (
            r[" ".join([pretext, "MATERIAL THICKNESS (m)"])]
            / r[" ".join([pretext, "MATERIAL THERMAL CONDUCTIVITY (W/m/K)"])]
        )
        insulation_resistance = (
            r[" ".join([pretext, "INSULATION MATERIAL THICKNESS (m)"])]
            / r[" ".join([pretext, "INSULATION MATERIAL THERMAL CONDUCTIVITY (W/m/K)"])]
        )
        # Internal structures assume no insulation.
        if self.structure_types.loc[st, "is_internal"]:
            intR = (
                self.interior_node_depth * 0.5 * material_resistance
                + self.structure_types.loc[st, "interior_resistance_m2K_W"]
            )
            extR = (
                2 - self.interior_node_depth
            ) * 0.5 * material_resistance + self.structure_types.loc[
                st, "exterior_resistance_m2K_W"
            ]
            return (1.0 / extR, 0.0, 1.0 / intR, 1.0 / (extR + intR))
        elif st == "base_floor":  # Base floor connects to the ground.
            intR = (
                self.interior_node_depth
                * (material_resistance + 0.5 * insulation_resistance)
                + self.structure_types.loc[st, "interior_resistance_m2K_W"]
            )
            flrR = (
                material_resistance
                + insulation_resistance
                + self.structure_types.loc[st, "interior_resistance_m2K_W"]
            )
            grnR = 1.0 / (0.114 / (0.7044 + flrR) + 0.8768 / (2.818 + flrR))
            grnR -= intR
            return (0.0, 1.0 / grnR, 1.0 / intR, 1.0 / (intR + grnR))
        else:  # Other structures connect to the ambient air.
            intR = (
                self.interior_node_depth
                * (material_resistance + 0.5 * insulation_resistance)
                + self.structure_types.loc[st, "interior_resistance_m2K_W"]
            )
            extR = (
                material_resistance
                + insulation_resistance
                + self.structure_types.loc[st, "interior_resistance_m2K_W"]
                + self.structure_types.loc[st, "exterior_resistance_m2K_W"]
                - intR
            )
            return (1.0 / extR, 0.0, 1.0 / intR, 1.0 / (extR + intR))

    def calculate_structure_statistics(self):
        """
        Process structural statistics from data for ArchetypeBuildingModel.jl.

        Returns
        -------
        structural_statistics
            a DataFrame for structure_statistics.csv export.
        """
        return (
            pd.DataFrame(
                [
                    [
                        r["building_type"],
                        r["building_period"],
                        r["location_id"],
                        st,
                        r["material_combination_weight"]
                        * r[
                            " ".join(
                                [
                                    "REFERENCE BUILDING",
                                    self.structure_types.loc[st, "mapping"],
                                    "U-VALUE (W/m2/K)",
                                ]
                            )
                        ],
                        r["material_combination_weight"]
                        * self.calculate_weighted_effective_thermal_mass(
                            r,
                            st,
                        ),
                        r["material_combination_weight"]
                        * self.structure_types.loc[st, "linear_thermal_bridge_W_mK"],
                    ]
                    + [
                        r["material_combination_weight"] * x
                        for x in self.calculate_U_values(r, st)
                    ]
                    for ((i, r), st) in product(
                        self.data.iterrows(), self.structure_types.index
                    )
                ],
                columns=[
                    "building_type",
                    "building_period",
                    "location_id",
                    "structure_type",
                    "design_U_value_W_m2K",
                    "effective_thermal_mass_J_m2K",
                    "linear_thermal_bridges_W_mK",
                    "external_U_value_to_ambient_air_W_m2K",
                    "external_U_value_to_ground_W_m2K",
                    "internal_U_value_to_structure_W_m2K",
                    "total_U_value_W_m2K",
                ],
            )
            .groupby(
                ["building_type", "building_period", "location_id", "structure_type"]
            )
            .agg(
                {
                    "design_U_value_W_m2K": "sum",
                    "effective_thermal_mass_J_m2K": "sum",
                    "linear_thermal_bridges_W_mK": "sum",
                    "external_U_value_to_ambient_air_W_m2K": "sum",
                    "external_U_value_to_ground_W_m2K": "sum",
                    "internal_U_value_to_structure_W_m2K": "sum",
                    "total_U_value_W_m2K": "sum",
                }
            )
        )

    def calculate_ventilation_and_fenestration_statistics(self):
        """
        Process ventilation and fenestration statistics for ArchetypeBuildingModel.jl.

        Returns
        -------
        ventilation_and_fenestration_statistics
            a DataFrame for `ventilation_and_fenestration_statistics.csv` export.
        """
        return (
            pd.DataFrame(
                [
                    [
                        r["building_type"],
                        r["building_period"],
                        r["location_id"],
                        r["material_combination_weight"]
                        * self.ventilation["HRU_efficiency"][0],
                        r["material_combination_weight"]
                        * self.ventilation["infiltration_rate_1_h"][0],
                        r["material_combination_weight"]
                        * self.fenestration.loc[
                            (
                                r["REFERENCE BUILDING WINDOW GLAZING TYPE"],
                                r["REFERENCE BUILDING WINDOW COATED"],
                            ),
                            "normal_solar_energy_transmittance",
                        ]
                        * (
                            1
                            - self.fenestration.loc[
                                (
                                    r["REFERENCE BUILDING WINDOW GLAZING TYPE"],
                                    r["REFERENCE BUILDING WINDOW COATED"],
                                ),
                                "frame_area_fraction",
                            ]
                        ),
                        r["material_combination_weight"]
                        * self.ventilation["ventilation_rate_1_h"][0],
                        r["material_combination_weight"]
                        * r["REFERENCE BUILDING WINDOW U-VALUE (W/m2/K)"],
                    ]
                    for (i, r) in self.data.iterrows()
                ],
                columns=[
                    "building_type",
                    "building_period",
                    "location_id",
                    "HRU_efficiency",
                    "infiltration_rate_1_h",
                    "total_normal_solar_energy_transmittance",
                    "ventilation_rate_1_h",
                    "window_U_value_W_m2K",
                ],
            )
            .groupby(["building_type", "building_period", "location_id"])
            .agg(
                {
                    "HRU_efficiency": "sum",
                    "infiltration_rate_1_h": "sum",
                    "total_normal_solar_energy_transmittance": "sum",
                    "ventilation_rate_1_h": "sum",
                    "window_U_value_W_m2K": "sum",
                }
            )
        )


class ABMDataset:
    """An object class for containing and exporting ArchetypeBuildingModel.jl compatible data."""

    def __init__(self, ambdata):
        """
        Process the AmBIENCe project raw data for ArchetypeBuildingModel.jl.

        Parameters
        ----------
        ambdata : AmBIENCeDataset
            the pre-processed AmBIENCe dataset used as the basis for the ABM.jl data.
        """
        self.building_period = ambdata.building_periods()
        self.building_stock = ambdata.building_stocks()
        self.structure_type = ambdata.structure_types.drop(columns=["mapping"])
        self.building_stock_statistics = ambdata.calculate_building_stock_statistics()
        self.structure_statistics = ambdata.calculate_structure_statistics()
        self.ventilation_and_fenestration_statistics = (
            ambdata.calculate_ventilation_and_fenestration_statistics()
        )
        self.location_id = (
            ambdata.data[["location_id"]].drop_duplicates().set_index("location_id")
        )
        self.shapefile_mappings = ambdata.shapefile_mappings
        self.building_type_mappings = ambdata.building_type_mappings

    def export_csvs(self, folderpath="data/"):
        """
        Export the ABMDataset contents as .csv files.

        Parameters
        ----------
        folderpath : str
            the folder path where to export the contents.

        Returns
        -------
        a bunch of .csv files as output, but the function returns nothing.
        """
        self.building_period.sort_index().to_csv(folderpath + "building_period.csv")
        self.building_stock.sort_index().to_csv(folderpath + "building_stock.csv")
        self.structure_type.sort_index().to_csv(folderpath + "structure_type.csv")
        self.building_stock_statistics.sort_index().to_csv(
            folderpath + "building_stock_statistics.csv"
        )
        self.structure_statistics.sort_index().to_csv(
            folderpath + "structure_statistics.csv"
        )
        self.ventilation_and_fenestration_statistics.sort_index().to_csv(
            folderpath + "ventilation_and_fenestration_statistics.csv"
        )
        self.location_id.sort_index().to_csv(folderpath + "location_id.csv")

    def create_datapackage(self, folderpath="data/"):
        """
        Create and infer a DataPackage from exported .csv files.

        Parameters
        ----------
        folderpath : str
            the folder path of the DataPackage contents.

        Returns
        -------
        pkg
            a Package object with contents and metadata.
        """
        pkg = Package(folderpath + "*.csv")
        pkg.infer()
        pkg.name = "ambience2abm_data"
        pkg.licenses = [
            {
                "name": "CC-BY-4.0",
                "path": "https://creativecommons.org/licenses/by/4.0/",
                "title": "Creative Commons Attribution 4.0",
            }
        ]
        pkg.profile = "data-package"
        pkg.title = "AmBIENCe2ABM building stock data"
        pkg.description = "A building stock data package processed from AmBIENCe project EU27 data for use with ArchetypeBuildingModel.jl."
        pkg.homepage = "https://github.com/spine-tools/AmBIENCe2ABM.jl"
        pkg.version = __version__
        pkg.sources = [
            {
                "name": "D4.1 Database of grey-box model parameter values for EU building typologies",
                "web": "https://ambience-project.eu/wp-content/uploads/2022/02/AmBIENCe_D4.1_Database-of-grey-box-model-parameter-values-for-EU-building-typologies-update-version-2-submitted.pdf",
            },
            {
                "name": "Database of grey-box model parameters",
                "web": "https://ambience-project.eu/wp-content/uploads/2022/03/AmBIENCe_Deliverable-4.1_Database-of-greybox-model-parameter-values.xlsx",
            },
            {
                "name": "D4.2 - Buildings Energy Systems Database EU27",
                "web": "https://ambience-project.eu/wp-content/uploads/2022/06/AmBIENCe-WP4-T4.2-Buildings_Energy_systems_Database_EU271.xlsx",
            },
        ]
        pkg.contributors = [
            {
                "title": "Topi Rasku",
                "email": "topi.rasku@vtt.fi",
                "path": "https://cris.vtt.fi/en/persons/topi-rasku",
                "role": "author",
                "organization": "VTT Technical Research Centre of Finland Ltd",
            }
        ]
        pkg.keywords = [
            "European Union",
            "EU",
            "Building stock",
            "Building structures",
            "Fenestration",
            "Construction",
            "AmBIENCe",
            "Hotmaps",
            "Mopo",
            "ABM.jl",
            "ArchetypeBuildingModel.jl",
        ]
        pkg.created = datetime.today().isoformat()
        return pkg
