# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-TODAY OpenERP S.A. <http://www.openerp.com>
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

from osv import fields, osv
from datetime import datetime, time
import tools
from tools.translate import _
from openerp.addons.metro import mdb
from openerp.tools.misc import resolve_attr

class hr_employee(osv.osv):
	_inherit = "hr.employee"

	def _get_leave_status(self, cr, uid, ids, name, args, context=None):
		holidays_obj = self.pool.get('hr.holidays')
		#fix the time interval query parameter issue
		''' old code
		holidays_id = holidays_obj.search(cr, uid,
		   [('employee_id', 'in', ids), ('date_from','<=',time.strftime('%Y-%m-%d %H:%M:%S')),
		   ('date_to','>=',time.strftime('%Y-%m-%d 23:59:59')),('type','=','remove'),('state','not in',('cancel','refuse'))],
		   context=context)
		'''
		now = datetime.utcnow()
		holidays_id = holidays_obj.search(cr, uid,
		   [('employee_id', 'in', ids), ('date_from','<=',now.strftime('%Y-%m-%d %H:%M:%S')),
		   ('date_to','>=',now.strftime('%Y-%m-%d %H:%M:%S')),('type','=','remove'),('state','not in',('cancel','refuse'))],
		   context=context)		
		result = {}
		for id in ids:
		    result[id] = {
		        'current_leave_state': False,
		        'current_leave_id': False,
		        'leave_date_from':False,
		        'leave_date_to':False,
		    }
		for holiday in self.pool.get('hr.holidays').browse(cr, uid, holidays_id, context=context):
		    result[holiday.employee_id.id]['leave_date_from'] = holiday.date_from
		    result[holiday.employee_id.id]['leave_date_to'] = holiday.date_to
		    result[holiday.employee_id.id]['current_leave_state'] = holiday.state
		    result[holiday.employee_id.id]['current_leave_id'] = holiday.holiday_status_id.id
		return result
	_columns = {
		'employment_start':fields.date('Employment Started'),
        'employment_resigned':fields.date('Employment Resigned'),
		'employment_finish':fields.date('Employment Finished'),
		'salaryhistory_ids': fields.one2many('hr.employee.salaryhistory', 'salary_id', 'Salary History'),
		#need to copy the below columns here since redefine the method _get_leave_status
		'current_leave_state': fields.function(_get_leave_status, multi="leave_status", string="Current Leave Status", type="selection",
			selection=[('draft', 'New'), ('confirm', 'Waiting Approval'), ('refuse', 'Refused'),
			('validate1', 'Waiting Second Approval'), ('validate', 'Approved'), ('cancel', 'Cancelled')]),
		'current_leave_id': fields.function(_get_leave_status, multi="leave_status", string="Current Leave Type",type='many2one', relation='hr.holidays.status'),
		'leave_date_from': fields.function(_get_leave_status, multi='leave_status', type='date', string='From Date'),
		'leave_date_to': fields.function(_get_leave_status, multi='leave_status', type='date', string='To Date'),
		'emp_code': fields.char('Employee Code', size=16),
		'emp_card_id': fields.char('Employee Card ID', size=16),		
	}
	_sql_constraints = [
		('emp_code_uniq', 'unique(emp_code)', 'Employee Code must be unique!'),
	]	
	def default_get(self, cr, uid, fields_list, context=None):
		values = super(hr_employee,self).default_get(cr, uid, fields_list, context)
		cr.execute("SELECT max(id) from hr_employee")
		emp_id = cr.fetchone()
		emp_code = '%03d'%(emp_id[0] + 1,)
		values.update({'emp_code':emp_code})
		return values
	
	def sync_clock(self, cr, uid, ids=None, context=None):
		if not context:
			context = {}
		if not ids:
			ids = self.search(cr, uid, [('active','=',True)], context = context)
		#get the clock data
		file_name = self.pool.get('ir.config_parameter').get_param(cr, uid, 'hr_clock_mdb_file', context=context)
		conn = mdb.open_conn(file_name)
		sql = "select userid,badgenumber,name,gender,ssn,minzu,ophone,title,birthday,hiredday,cardno,pager,street from userinfo"
		emps_clock, fld_size = mdb.exec_query(conn, sql, 'ssn')
		if len(fld_size) == 0:
			fld_size = {'badgenumber':24,
						'name':40,
						'gender':8,
						'ssn':20,
						'minzu':8,
						'ophone':20,
						'title':20,
						'birthday':-1,
						'hiredday':-1,
						'cardno':20,
						'pager':20,
						'street':80,
						'badgenumber':24,
						'name':40,
						'gender':8,
						'ssn':20,
						'minzu':8,
						'ophone':20,
						'title':20,
						'birthday':-1,
						'hiredday':-1,
						'cardno':20,
						'pager':20,
						'street':80,
						}
		#compare the data, and push the chaning to clock
		check_attrs = {'badgenumber':'emp_code',
						'name':'name',
						'gender':'gender',
						'ssn':'emp_code',
						'minzu':'',
						'ophone':'work_phone',
						'title':'job_id.name',
						'birthday':'birthday',
						'hiredday':'employment_start',
						'cardno':'emp_card_id',
						'pager':'mobile_phone',
						'street':'address_home_id.name',
						}
		for emp in self.browse(cr, uid, ids, context=context):
			if not emps_clock.has_key(emp.emp_code):
				#do insert
				cols = ''
				vals = ''
				for attr in check_attrs:
					cols = cols + attr + ','
					attr_val = ''
					if check_attrs[attr] != '':
						attr_val = resolve_attr(emp,check_attrs[attr]) or ''
						if fld_size[attr] > 0:
							attr_val = attr_val[:fld_size[attr]] 
					if attr == 'gender':
						if attr_val == 'male':
							attr_val = 'M'
						if attr_val == 'female':
							attr_val = 'F'
					vals = vals + '\'' +  attr_val + '\','				
				sql = 'insert into userinfo (%s) values(%s)'%(cols[:-1], vals[:-1])
				mdb.exec_ddl(conn, sql)
			else:
				#do update
				emp_clock = emps_clock[emp.emp_code]
				upt_cols = ''
				for attr in check_attrs:
					if check_attrs[attr] == '':
						continue
					attr_val = resolve_attr(emp,check_attrs[attr]) or ''
					if fld_size[attr] > 0:
						attr_val = attr_val[:fld_size[attr]] 
					attr_val_clock = emp_clock[attr]
					if attr == 'gender':
						if attr_val == 'male':
							attr_val = 'M'
						if attr_val == 'female':
							attr_val = 'F'
					if attr_val != attr_val_clock:
						upt_cols = upt_cols + attr + '=\'' + attr_val + '\','
				if upt_cols != '':
					upt_cols = upt_cols[:-1]
					sql = 'update userinfo set ' + upt_cols + ' where userid = ' + str(emp_clock['userid'])
					mdb.exec_ddl(conn, sql)
		mdb.close_conn(conn)
		return True
				
hr_employee()

class salary_history(osv.osv):
    _name = "hr.employee.salaryhistory"
    _description = "Employee Salary History"
    _columns = {
        'date' : fields.date('Date', required=True),
        'salary' : fields.char('Amount (CNY)', size=64),
		'reason' : fields.char('Reason for Change', size=64),
		'salary_id': fields.many2one('hr.employee', 'Test', ondelete='cascade'),
    }
    _order = 'date desc'
salary_history()

class hr_holiday_calendar(osv.osv):
    _name = "hr.employee.holidaycalendar"
    _description = "Holiday Calendar Dates"
    _columns  = {
        'date_stop':fields.date('Stop date', required=False),
        'date_start':fields.date('Start date', required=True),
        'name': fields.char('Holiday Name', size=512, required=True),
        'holidaytype': fields.selection([('chineseholiday','Chinese National Holiday'),('longjuholiday','Dongguan Longju Holiday'),('extraworkday','Extra Working Day')],'Holiday Type'),
        }
    _defaults = {'holidaytype': 'chineseholiday',
    }
hr_holiday_calendar() 

class res_users(osv.osv):
    _name = 'res.users'
    _inherit = 'res.users'
    def copy(self, cr, uid, id, default=None, context=None):
		default.update({'employee_ids':[]})
		return super(res_users,self).copy(cr, uid, id, default, context)