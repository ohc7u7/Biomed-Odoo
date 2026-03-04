# -*- coding: utf-8 -*-
# [FIX] password=True eliminado — no es parámetro válido en Odoo 18.
# La ocultación visual se hace con widget="password" en la vista XML.
from odoo import models, fields
from odoo.exceptions import UserError
import requests


class BiomedConfigWizard(models.TransientModel):
    _name = 'biomed.config.wizard'
    _description = 'Configuración BioMed — API Key Gemini'

    # password=True removido — usamos widget="password" en la vista
    gemini_api_key = fields.Char(string='API Key de Google Gemini', required=True)
    test_result = fields.Html(string='Resultado de prueba', readonly=True)

    def action_save_and_test(self):
        self.ensure_one()
        key = self.gemini_api_key.strip()
        if len(key) < 20:
            raise UserError("La API Key parece inválida (muy corta).")

        test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        try:
            resp = requests.get(test_url, timeout=10)
            if resp.status_code == 200:
                self.env['ir.config_parameter'].sudo().set_param(
                    'farmacia_bio.gemini_api_key', key
                )
                self.test_result = (
                    '<div style="color:green;font-weight:bold;">'
                    '✅ API Key válida y guardada correctamente.</div>'
                )
            elif resp.status_code == 400:
                raise UserError("API Key inválida. Verifica en Google AI Studio.")
            else:
                raise UserError(f"Error al verificar la key: HTTP {resp.status_code}")
        except requests.exceptions.Timeout:
            raise UserError("No se pudo conectar a Google. Verifica tu conexión.")

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'biomed.config.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }