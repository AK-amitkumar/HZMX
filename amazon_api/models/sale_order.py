# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
import datetime
from odoo.addons.amazon_api.amazon_api.mws import Feeds

class SaleOrder(models.Model):
    _inherit = "sale.order"

    e_order = fields.Char(string=u'电商订单号')
    province = fields.Char(string=u'州／省')
    city = fields.Char(string=u'市')
    street = fields.Char(string=u'街道')
    postal_code = fields.Char(string=u'邮编')
    phone = fields.Char(string=u'电话')
    e_mail = fields.Char(string=u'邮箱')

    sale_date = fields.Datetime(string=u'下单日期')
    confirm_date = fields.Datetime(string=u'确认日期')

    e_order_amount = fields.Float(string=u'订单金额')
    e_order_freight = fields.Float(compute='_e_order_freight', store=False, string=u'运费')
    e_order_commission = fields.Float(compute='_e_order_commission', store=False, string=u'佣金')

    hide_platform_purchase_button = fields.Boolean(compute='_hide_platform_purchase_button', string=u'隐藏平台采购按钮')
    hide_myself_delivery_button = fields.Boolean(compute='_hide_myself_delivery_button', string=u'隐藏自有发货按钮')

    country_id = fields.Many2one('amazon.country', string=u'国家')
    shop_id = fields.Many2one('amazon.shop', string=u'店铺')
    e_currency_id = fields.Many2one('amazon.currency', related='shop_id.currency_id', string=u'币种')
    operator_id = fields.Many2one('res.users', default=lambda self: self.env.user, string=u'操作员')
    merchant_id = fields.Many2one('res.users', default=lambda self: self.env.user.merchant_id or self.env.user,
                                  string=u'商户')

    platform = fields.Selection([
        ('amazon', u'亚马逊'),
        ('ebay', u'Ebay')], default='amazon', string=u'来源平台')
    delivery_mode = fields.Selection([
        ('MFN', u'自发货'),
        ('FBA', u'FBA')], default='MFN', string=u'运输方式')
    amazon_state = fields.Selection([
        ('PendingAvailability', u'PendingAvailability'),
        ('Pending', u'Pending'),
        ('Unshipped', u'Unshipped'),
        ('PartiallyShipped', u'PartiallyShipped'),
        ('Shipped', u'Shipped'),
        ('InvoiceUnconfirmed', u'InvoiceUnconfirmed'),
        ('Canceled', u'Canceled'),
        ('Unfulfillable', u'Unfulfillable'),
    ], string=u'亚马逊订单状态')
    shipment_service_level_category = fields.Selection([
        ('Expedited', 'Expedited'),
        ('NextDay', 'NextDay'),
        ('SecondDay', 'SecondDay'),
        ('Standard', 'Standard'),
        ('FreeEconomy', 'FreeEconomy')], string=u"货运服务等级", default='Standard')
    delivery_upload_state = fields.Selection([
        ('wait_upload', u'待上传'),
        ('uploading', u'正在上传'),
        ('done', u'完成'),
        ('failed', u'失败')], default='wait_upload', string=u'发货信息上传状态')

    @api.multi
    def _e_order_commission(self):
        for order in self:
            order.e_order_commission = order.e_order_amount * 0.15

    @api.multi
    def _e_order_freight(self):
        for order in self:
            freight = 0
            for line in order.order_line:
                freight += line.e_freight
            order.e_order_freight = freight

    @api.multi
    def _hide_platform_purchase_button(self):
        for order in self:
            order.hide_platform_purchase_button = True
            for line in order.order_line:
                if not line.own_product:
                    order.hide_platform_purchase_button = False

    @api.multi
    def _hide_myself_delivery_button(self):
        for order in self:
            order.hide_myself_delivery_button = True
            for line in order.order_line:
                if line.own_product:
                    order.hide_myself_delivery_button = False

    @api.multi
    def false_delivery(self):
        '''假发货'''
        self.ensure_one()
        return {
            'name': u'假发货',
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.wizard',
            'view_mode': 'form',
            'view_type': 'form',
            'views': [(self.env.ref('amazon_api.false_delivery_wizard').id, 'form')],
            'target': 'new',
        }

    @api.model
    def search(self, args, offset=0, limit=None, order=None, count=False):
        context = self.env.context
        if context.get('view_own_data'):
            user = self.env.user
            if user.user_type == 'operator':
                shop_ids = user.shop_ids.ids
                args += [('shop_id', 'in', shop_ids)]
            elif user.user_type == 'merchant':
                shop_ids = []
                for operator in user.operator_ids:
                    shop_ids += operator.shop_ids.ids
                args += [('shop_id', 'in', shop_ids)]
        return super(SaleOrder, self).search(args, offset, limit, order, count=count)

    @api.multi
    def platform_purchase(self):
        '''平台采购'''
        self.ensure_one()
        purchase_obj = self.env['purchase.order']
        loc_obj = self.env['stock.location']
        stock_picking_obj = self.env['stock.picking']
        purchase_info = {}
        for sale_line in self.order_line:
            supplier_id = sale_line.sudo().product_id.product_tmpl_id.merchant_id.partner_id.id
            if purchase_info.has_key(supplier_id):
                purchase_info[supplier_id]['order_line'].append((0, 0, {
                    'product_id': sale_line.product_id.id,
                    'name': sale_line.product_id.name,
                    'price_unit': sale_line.product_id.platform_price,
                    'product_qty': sale_line.product_uom_qty,
                    'product_uom': sale_line.product_uom.id,
                    'date_planned': datetime.datetime.now(),
                }))
            else:
                purchase_info[supplier_id] = {
                    'partner_id': supplier_id,
                    'currency_id': self.currency_id.id,
                    'date_order': datetime.datetime.now(),
                    'date_planned': datetime.datetime.now(),
                    'order_line': [(0, 0, {
                        'product_id': sale_line.product_id.id,
                        'name': sale_line.product_id.name,
                        'price_unit': sale_line.product_id.platform_price,
                        'product_qty': sale_line.product_uom_qty,
                        'product_uom': sale_line.product_uom.id,
                        'date_planned': datetime.datetime.now(),
                    })]
                }
        for (supplier_id, val) in purchase_info.items():
            print val
            purchase_order = purchase_obj.create(val)
            print purchase_order
            #create delivery
            location_id = loc_obj.search([
                ('partner_id', '=', supplier_id),
                ('location_id', '=', self.env.ref('b2b_platform.supplier_stock').id)], limit=1).id
            location_dest_id = self.env.ref('stock.stock_location_customers').id
            delivery_info = {
                'partner_id': purchase_order.partner_id.id,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'picking_type_id': 3,
                'move_lines': [],
            }
            for pur_line in purchase_order.order_line:
                delivery_info['move_lines'].append((0, 0, {
                    'product_id': pur_line.product_id.id,
                    'name': pur_line.product_id.name,
                    'product_uom_qty': pur_line.product_qty,
                    'product_uom': pur_line.product_uom.id,
                }))
            stock_picking_obj.create(delivery_info)
        return
