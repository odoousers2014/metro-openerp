# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields, osv
from openerp.tools.translate import _

class account_period_close_entry(osv.osv_memory):
    """
    Generate Closing entries for The period will be close
    """
    _name = "account.period.close.entry"
    _description = "Generate Period Closing Entries"
    _columns = {
       'period_id': fields.many2one('account.period', 'Closing Period', required=True, readonly=True),
       'journal_id': fields.many2one('account.journal', 'Closing Journal', domain="[('company_id','=', company_id),('period_close','=', True), ('type','=','situation'),('centralisation','=',True)]", required=True),
       'notes': fields.char('Notes',size=64, required=True),       
       'company_id': fields.many2one('res.company', 'Company', required=True, select=1, help="Company related to this journal"),
       'auto_opt': fields.selection([('none','None'),('post','Post Entry'),('post_close','Post Entry and Close Period')], 'Auto options', required=True),
    }
    _defaults={'auto_opt':'none'}
    
    def default_get(self, cr, uid, fields, context=None):
        defaults = super(account_period_close_entry, self).default_get(cr, uid, fields, context=context)
        if not defaults:
            defaults = {}
            
        defaults['notes'] =  _('Period closing entry')
        company_id = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.id
            
        if 'period_id' in fields:
            period_obj = self.pool.get('account.period')
            #find the earliest period that not done, 第一个打开的会计期间
            period_ids = period_obj.search(cr, uid, [ ('state','!=','done'), ('company_id','=',company_id), ('special','=',False)], order='date_start', limit=1, context=context)
            if period_ids:
                defaults['period_id'] = period_ids[0]
                period_name = period_obj.read(cr, uid, period_ids[0], ['name'], context=context)['name']
                defaults['notes'] = _('Period closing entry for %s')%(period_name,)
        if not defaults.get('period_id'):
            raise osv.except_osv(_('Error!'), _('No available period was found, please close the period that generated closing entry in time'))
        
        #月结账簿-默认为本公司的period_close=1, type=('situation', 'Opening/Closing Situation'), centralisation=True的account_journal         
        if 'journal_id' in fields:
            domain = [('company_id', '=', company_id), ('period_close', '=', True), ('type', '=', 'situation'), ('centralisation', '=', True)]
            journal_ids = self.pool.get('account.journal').search(cr, uid, domain, context=context)
            if journal_ids:
                defaults['journal_id'] = journal_ids[0]
        
        #default to user's company
        if 'company_id' in fields:    
            defaults['company_id'] = company_id 

        return defaults

    def data_save(self, cr, uid, ids, context=None):
        """
        This function create closing entries for one period
        """

        obj_acc_period = self.pool.get('account.period')
        obj_acc_move = self.pool.get('account.move')
        obj_acc_move_line = self.pool.get('account.move.line')
        obj_acc_account = self.pool.get('account.account')
        obj_acc_journal_period = self.pool.get('account.journal.period')
        currency_obj = self.pool.get('res.currency')

        data = self.browse(cr, uid, ids, context=context)[0]
        company = data.company_id
        journal = data.journal_id
        period = data.period_id

        if context is None:
            context = {}
        #delete the entry closing account move if exist
        if  period.close_move_id:
            if period.close_move_id.state == 'posted':
                obj_acc_move.button_cancel(cr, uid, [period.close_move_id.id],context=context)
            obj_acc_move.unlink(cr, uid, [period.close_move_id.id],context=context)
        #if there are any existing draft moves of this period, then report one error message
        draft_move_ids = obj_acc_move.search(cr, uid, [('period_id', '=', period.id), ('state', '!=', "posted")], context=context)
        if draft_move_ids:
            raise osv.except_osv(_('Error!'), _('In order to close a period, you must first post related journal entries.'))
        #if period closing parameters are missing, then raise error
        if not company.period_close_type or not company.income_account_types  or not company.expense_account_types:
            raise osv.except_osv(_('Error!'), _('Please set the period closing parameter for company %s')%(company.name))
        
        #if period_close_type is year, then update period and exit directly
        if company.period_close_type == 'year':
            obj_acc_period.write(cr, uid, data.period_id.id, {'close_entry_done':True}, context=context)
            return {'type': 'ir.actions.act_window_close'}
        
        #journal's restriction checking
        if not journal.default_credit_account_id or not journal.default_debit_account_id:
            raise osv.except_osv(_('User Error!'),_('The journal must have default credit and debit account.'))
        if (not journal.centralisation) or journal.entry_posted or not journal.period_close:
            raise osv.except_osv(_('User Error!'),_('The journal must have centralized counterpart without the Skipping draft state option checked and for period close.'))            
            
        #create the opening move
        vals = {
            'name': '/',
            'journal_id': journal.id,
            'period_id': period.id,
            'date': period.date_stop,
            'narration': data.notes,
            'company_id': company.id
        }
        move_id = obj_acc_move.create(cr, uid, vals, context=context)
        
        query_line = obj_acc_move_line._query_get(cr, uid,obj='account_move_line', context={'periods': [period.id]}) 
        
        def _add_move_lines():
            #add the account(income/expense) balance move lines
            account_ids = obj_acc_account.search(cr, uid, [('user_type', 'in', account_type_ids), ('type', '!=', 'view'), ('company_id', '=', company.id)], context=context)
            balance_total = 0.0
            balance_in_currency_total = 0.0
            for account in obj_acc_account.browse(cr, uid, account_ids, context={'periods': [period.id]}):
                balance = account.balance
                balance_total += account.balance
                balance_in_currency = 0.0
                debit = 0.0
                credit = 0.0
                if account.currency_id:
                    cr.execute('SELECT sum(COALESCE(amount_currency,0.0)) as balance_in_currency FROM account_move_line ' \
                            'WHERE account_id = %s ' \
                                'AND ' + query_line + ' ' \
                                'AND currency_id = %s', (account.id, account.currency_id.id))
                    balance_in_currency = cr.dictfetchone()['balance_in_currency']
                    balance_in_currency_total += balance_in_currency
    
                company_currency_id = company.currency_id
                if not currency_obj.is_zero(cr, uid, company_currency_id, abs(account.balance)):
                    if bal_direct == 'credit':
                        #for the incoming, the balance should be in credit
                        balance_in_currency = -balance_in_currency
                        balance = -account.balance
                        #record the amount to the opposite direct
                        debit = balance>0 and balance or 0
                        credit = balance<0 and -balance or 0
                    else:
                        #for the expense, the balance should be in debit
                        #record the amount to the opposite direct
                        debit = balance<0 and -balance or 0
                        credit = balance>0 and balance or 0
                        
                    vals = {'move_id':move_id, 'name':move_line_name, 'account_id':account.id,
                            'debit': debit, 'credit': credit, 'amount_currency':balance_in_currency}
                    obj_acc_move_line.create(cr, uid, vals, context=context)
                
            #add the profit move lines as the counterpart of the above move lines
            if balance_total > 0:
                balance = balance_total
                balance_in_currency = balance_in_currency_total
                if bal_direct == 'credit':
                    #for the incoming, the balance should be in credit
                    balance = -balance
                    #record the profit amount
                    debit = balance<0 and -balance or 0
                    credit = balance>0 and balance or 0
                    account_id = balance>0 and journal.default_crediit_account_id or journal.default_debit_account_id
                else:
                    #for the expense, the balance should be in debit
                    #record the profit amount
                    debit = balance>0 and balance or 0
                    credit = balance<0 and -balance or 0
                    account_id = balance>0 and journal.default_debit_account_id or journal.default_crediit_account_id
                vals = {'move_id':move_id, 'name':move_line_profit_name, 'account_id':account_id.id,
                        'debit': debit, 'credit': credit, 'amount_currency':balance_in_currency}
                obj_acc_move_line.create(cr, uid, vals, context=context)
        
        move_line_profit_name = _('period close profit transfer - %s')%(period.name,)
        
        #add move lines for incoming accounts balance
        account_type_ids = [account_type.id for account_type in company.income_account_types]
        bal_direct = 'credit'
        move_line_name = _('period close income transfer %s')%(period.name,)
        _add_move_lines()
        #add move lines for expense accounts balance
        account_type_ids = [account_type.id for account_type in company.expense_account_types]
        bal_direct = 'debit'
        move_line_name = _('period close expense transfer %s')%(period.name,)
        _add_move_lines()        
        
        period_vals = {}
        #validate the account move
        move = obj_acc_move.browse(cr, uid, move_id, context=context)
        if not move.line_id:
            #if there are no move lines, then remove the created move
            obj_acc_move.unlink(cr, uid, [move_id], context=context)
        else:
            obj_acc_move.validate(cr, uid, [move_id], context=context)
            #create the journal.period object and link it to the old fiscalyear
            journal_period_ids = obj_acc_journal_period.search(cr, uid, [('journal_id', '=', journal.id), ('period_id', '=', period.id)])
            if not journal_period_ids:
                journal_period_ids = [obj_acc_journal_period.create(cr, uid, {
                       'name': (journal.name or '') + ':' + (period.code or ''),
                       'journal_id': journal.id,
                       'period_id': period.id
                   })]        
            period_vals.update({'close_journal_period_id':journal_period_ids[0], 'close_move_id': move_id})
            
        #update period closing data
        period_vals.update({'close_entry_done':True})
        obj_acc_period.write(cr, uid, period.id, period_vals, context=context)
        
        #auto post the closing entry
        if move.line_id and data.auto_opt in('post', 'post_close'):
            obj_acc_move.post(cr, uid, [move.id], context=context)
            
        #auto close the period
        if data.auto_opt == 'post_close':
            period_close_obj = self.pool.get('account.period.close')
            #create close object
            c = context.copy()
            c['active_ids'] = [period.id]
            period_close_id = period_close_obj.create(cr, uid, {'sure':True}, context=c)
            #do close
            period_close_obj.data_save(cr, uid, [period_close_id], context=c)
            #delete the wizard data
            period_close_obj.unlink(cr, uid, [period_close_id], context=c)

        return {'type': 'ir.actions.act_window_close'}

account_period_close_entry()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
