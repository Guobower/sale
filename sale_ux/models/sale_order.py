##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import models, api, fields, _
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pricelist_id = fields.Many2one(
        track_visibility='onchange',
    )
    payment_term_id = fields.Many2one(
        track_visibility='onchange',
    )
    force_invoiced_status = fields.Selection([
        ('no', 'Nothing to Invoice'),
        ('invoiced', 'Fully Invoiced')],
        track_visibility='onchange',
        copy=False,
    )
    commercial_partner_id = fields.Many2one(
        'res.partner',
        string='Commercial Entity',
        related='partner_id.commercial_partner_id',
        store=True,
        readonly=True,
    )

    @api.depends('order_line.price_total')
    def _amount_all(self):
        """
        Hacemos esto para disponer de fecha del pedido y cia para calcular
        impuesto con código python (por ej. para ARBA).
        Aparentemente no se puede cambiar el contexto a cosas que se llaman
        desde un onchange (ver https://github.com/odoo/odoo/issues/7472)
        entonces usamos este artilugio
        TODO este cambio seria mas correcto que este en un repo de loc
        argentina pero para no hacer un modulo con tan pocas cosas lo
        hacemos acá, ademas que el repo de odoo-argentina da error en los tests
        si se instala sale (entonces no podemos agregar dep a sale por ahora)
        """
        # no estoy seguro porque pero al mandar email template algunas veces
        # llegan varias sale orders a esta funcion
        for rec in self:
            date_order = rec.date_order or fields.Date.context_today(rec)
            rec.env.context.date_invoice = date_order
            rec.env.context.invoice_company = rec.company_id
        return super(SaleOrder, self)._amount_all()

    @api.multi
    def action_cancel(self):
        invoices = self.mapped('invoice_ids').filtered(
            lambda x: x.state not in ['cancel', 'draft'])
        if invoices:
            raise UserError(_(
                "Unable to cancel this sale order. You must first "
                "cancel related bills and pickings."))
        return super(SaleOrder, self).action_cancel()

    @api.constrains('force_invoiced_status')
    def check_force_invoiced_status(self):
        group = self.sudo().env.ref('base.group_system')
        if self.force_invoiced_status and not self.user_has_groups(
                'base.group_system'):
            raise ValidationError(_(
                'Only users with "%s / %s" can Set Invoiced manually') % (
                group.category_id.name, group.name))

    @api.multi
    def action_confirm(self):
        # con esto arreglamos que odoo dejaria entregar varias veces el
        # mismo picking si por alguna razon el boton esta presente
        # en nuestro caso pasaba cuando la impresion da algun error
        # lo que provoca que el picking se entregue pero la pantalla no
        # se actualice
        # antes lo haciamo en do_new_transfer, pero como algunas
        # veces se llama este metodo sin pasar por do_new_transfer
        invoices = self.filtered(lambda x: x.state not in ['draft', 'sent'])
        if invoices:
            raise UserError(_(
                'You can not validate a sale that is not in a state '
                '"Quotation" or "Quotation Sent", probably'
                'has already been validated, try refreshing the window!'))
        return super(SaleOrder, self).action_confirm()

    @api.multi
    def update_prices(self):
        # for compatibility with product_pack module
        self.ensure_one()
        pack_installed = 'pack_parent_line_id' in self.order_line._fields
        for line in self.order_line:
            if pack_installed and line.pack_parent_line_id.\
                product_id.pack_price_type in [
                    'fixed_price', 'totalice_price']:
                price = 0.0
            else:
                price = self.pricelist_id.with_context(
                    uom=line.product_uom.id,
                    date=self.date_order).price_get(
                    line.product_id.id,
                    line.product_uom_qty or 1.0,
                    self.partner_id.id
                )[self.pricelist_id.id]
            line.update({'price_unit': price})
        return True
