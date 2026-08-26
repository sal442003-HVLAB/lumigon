"""Application-driven Product/Profile/Standard filtering for Lumigon Measurement.

The Measurement page should only expose definitions that belong to the selected
application.  Standards are intentionally concise in the Test Definition card;
profile-specific clauses, tables and calculation details belong in the profile
panel and Results workspace instead.
"""

from __future__ import annotations


ICAO_ANNEX_14 = "ICAO Annex 14"
BS_EN_12368 = "BS EN 12368:2024"


APPLICATION_CATALOG = {
    "Aviation": {
        "standard": ICAO_ANNEX_14,
        "products": {
            "Obstacle Light": [
                "MIOL Type A — ICAO Annex 14",
                "MIOL Type B — ICAO Annex 14",
                "MIOL Type C — ICAO Annex 14",
            ],
            "Airfield Ground Light": [
                "Airfield Ground Light — ICAO Annex 14",
            ],
            "Other / Custom": [
                "Custom Aviation Scan",
            ],
        },
    },
    "Road Traffic Signals": {
        "standard": BS_EN_12368,
        "products": {
            "Traffic Signal Head": [
                "Traffic Signal Head — BS EN 12368",
            ],
            "Pedestrian Signal Head": [
                "Pedestrian Signal Head — BS EN 12368",
            ],
            "Other / Custom": [
                "Custom Road Traffic Signal Scan",
            ],
        },
    },
    "Automotive Lighting": {
        # No automotive compliance profile has been assigned yet. Keep the
        # standard blank rather than presenting an unverified requirement.
        "standard": "",
        "products": {
            "Headlamp": ["Custom Automotive Headlamp Scan"],
            "Rear / Signal Lamp": ["Custom Automotive Signal Lamp Scan"],
            "Other / Custom": ["Custom Automotive Scan"],
        },
    },
}

CUSTOM_APPLICATION = "Custom Photometric Scan"


def _set_combo_items(combo, items, preferred=""):
    """Replace combo contents while preserving a matching selection if possible."""

    items = list(items)
    preferred = str(preferred or "")
    combo.blockSignals(True)
    combo.setEditable(False)
    combo.clear()
    combo.addItems(items)
    index = combo.findText(preferred)
    combo.setCurrentIndex(index if index >= 0 else (0 if items else -1))
    combo.blockSignals(False)


def attach_measurement_profile_catalog(window):
    """Filter Product/Profile/Standard from the selected Measurement application."""

    if getattr(window, "measurement_profile_catalog_attached", False):
        return

    application = getattr(window, "measurement_application_combo", None)
    product = getattr(window, "measurement_product_combo", None)
    profile = getattr(window, "measurement_profile_combo", None)
    standard = getattr(window, "measurement_standard_edit", None)
    if None in (application, product, profile, standard):
        raise RuntimeError("Measurement Test Definition controls are not available.")

    state = {
        "syncing": False,
        "custom_product": "",
        "custom_profile": "",
        "custom_standard": "",
    }

    def _emit_combo_change(combo):
        # The Measurement workspace and MIOL runtime already listen to this
        # signal. Emit once after a blocked catalog rebuild so they refresh
        # validation state and profile-specific controls using the final item.
        combo.currentIndexChanged.emit(combo.currentIndex())

    def _configure_custom():
        product.blockSignals(True)
        product.clear()
        product.setEditable(True)
        if product.lineEdit() is not None:
            product.lineEdit().setPlaceholderText("Enter product / device")
        product.setEditText(state["custom_product"])
        product.blockSignals(False)

        profile.blockSignals(True)
        profile.clear()
        profile.setEditable(True)
        if profile.lineEdit() is not None:
            profile.lineEdit().setPlaceholderText("Enter profile / test method")
        profile.setEditText(state["custom_profile"])
        profile.blockSignals(False)

        standard.setReadOnly(False)
        standard.setPlaceholderText("Enter standard / method (optional)")
        standard.setText(state["custom_standard"])

        _emit_combo_change(product)
        _emit_combo_change(profile)

    def _configure_predefined(app_name):
        catalog = APPLICATION_CATALOG[app_name]
        products = catalog["products"]

        previous_product = product.currentText()
        previous_profile = profile.currentText()
        _set_combo_items(product, products.keys(), previous_product)

        selected_product = product.currentText()
        allowed_profiles = products.get(selected_product, [])
        _set_combo_items(profile, allowed_profiles, previous_profile)

        standard.setReadOnly(True)
        standard.setPlaceholderText("")
        standard.setText(catalog["standard"])

        _emit_combo_change(product)
        _emit_combo_change(profile)

    def sync_application(*_args):
        if state["syncing"]:
            return
        state["syncing"] = True
        try:
            app_name = application.currentText()
            if app_name == CUSTOM_APPLICATION:
                _configure_custom()
            else:
                _configure_predefined(app_name)
        finally:
            state["syncing"] = False

    def sync_product(*_args):
        if state["syncing"] or application.currentText() == CUSTOM_APPLICATION:
            return
        app_name = application.currentText()
        catalog = APPLICATION_CATALOG.get(app_name)
        if catalog is None:
            return

        state["syncing"] = True
        try:
            allowed_profiles = catalog["products"].get(product.currentText(), [])
            previous_profile = profile.currentText()
            _set_combo_items(profile, allowed_profiles, previous_profile)
            standard.setReadOnly(True)
            standard.setText(catalog["standard"])
            _emit_combo_change(profile)
        finally:
            state["syncing"] = False

    def sync_standard(*_args):
        """Keep predefined Standard concise after profile/condition callbacks."""

        if state["syncing"]:
            return
        app_name = application.currentText()
        if app_name == CUSTOM_APPLICATION:
            return
        catalog = APPLICATION_CATALOG.get(app_name)
        if catalog is not None:
            standard.setReadOnly(True)
            standard.setText(catalog["standard"])

    def remember_custom_product(text):
        if application.currentText() == CUSTOM_APPLICATION and not state["syncing"]:
            state["custom_product"] = str(text)

    def remember_custom_profile(text):
        if application.currentText() == CUSTOM_APPLICATION and not state["syncing"]:
            state["custom_profile"] = str(text)

    def remember_custom_standard(text):
        if application.currentText() == CUSTOM_APPLICATION and not state["syncing"]:
            state["custom_standard"] = str(text)

    application.currentIndexChanged.connect(sync_application)
    product.currentIndexChanged.connect(sync_product)
    profile.currentIndexChanged.connect(sync_standard)
    product.currentTextChanged.connect(remember_custom_product)
    profile.currentTextChanged.connect(remember_custom_profile)
    standard.textChanged.connect(remember_custom_standard)

    # MIOL operating-condition changes rewrite the Standard field as part of
    # their detailed profile refresh. The Test Definition standard should stay
    # concise, so normalize it after that existing callback has run.
    condition = getattr(window, "measurement_miol_condition_combo", None)
    if condition is not None:
        condition.currentIndexChanged.connect(sync_standard)

    window.measurement_profile_catalog_attached = True
    sync_application()
