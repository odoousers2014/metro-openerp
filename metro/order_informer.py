# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
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
import logging
import base64

from datetime import datetime
from dateutil.relativedelta import relativedelta
import time
from socket import gethostname

from openerp.osv import fields,osv
from openerp.tools.config import config
from openerp.addons.base.ir.ir_config_parameter import ir_config_parameter

_logger = logging.getLogger(__name__)

class order_informer(osv.osv_memory):  
    _name="order.informer"
    def inform(self,cr,uid,order_type,context=None):
        if order_type == "purchase.order":
            return self._inform_po(cr,uid,)
    #get object ids, email subject & body, object creator emails
    def _get_body_subject(self,cr,uid,model,inform_type,email_tmpl_name,context=None):
        email_msg = None
        data_obj = self.pool.get(model)
        obj_ids = data_obj.search(cr,uid,[('inform_type','=',inform_type)],context=context)
        email_contacted_subject = ""
        email_subject = ""
        email_body = ""
        email_attachments = []
        email_creators = []
        email_tmpl_obj = self.pool.get('email.template')
        email_tmpl = email_tmpl_obj.search(cr,uid,[('name','=',email_tmpl_name)])[0]
        if obj_ids and len(obj_ids) > 0:
            objs = data_obj.browse(cr,uid,obj_ids,context=context)
            for obj in objs:
                if obj.partner_id:
                    obj.partner_id.lang='en_US'
                #get the values by template
                vals = email_tmpl_obj.generate_email(cr,uid,email_tmpl,obj.id,context=context)
                #use the 'email_recipients' as the the subject template that sent at last
                email_subject += vals['subject'] + ","
                email_contacted_subject = vals['email_recipients']
                email_body += vals['body']
                #decode the encoded the attachments
                for name,attachment in vals['attachments']:
                    email_attachments.append((name,base64.b64decode(attachment)))
                #add the creator email list
                try:
                    email_creators.index(obj.create_uid.email)
                except Exception:
                    if obj.create_uid.email:
                        email_creators.append(obj.create_uid.email)
            #replace the name
            email_subject = email_contacted_subject.replace('$list_names$', email_subject[:(len(email_subject)-1)])
            
        return obj_ids, email_subject, email_body, email_creators, email_attachments
    
    def _get_group_id_emails(self,cr,uid,group_ids,context):
            #get the group user's addresses by group id
            emails = []
            group_obj = self.pool.get("res.groups")
            if isinstance(group_ids, (int, long)):
                group_ids = [group_ids]
            groups = group_obj.browse(cr,uid,group_ids,context=context)
            for group in groups:
                for user in group.users:
                    if user.email: 
                        emails.append(user.email)
            return emails
    def _get_group_cata_name_emails(self,cr,uid,cata_name,group_name,context):
            #get the group user's addresses by group category and group name
            group_obj = self.pool.get("res.groups")
            group_cate_id = self.pool.get("ir.module.category").search(cr,uid,[("name","=",cata_name)])[0]
            if not group_cate_id:
                return False            
            group_ids = group_obj.search(cr,uid,[('category_id','=', group_cate_id),('name','=',group_name)],context=context)
            if not group_ids:
                return False
            return self._get_group_id_emails(cr,uid,group_ids[0],context)
                                        
                        
    def _send_emails(self,cr,uid,msgs,context):
        ir_mail_server = self.pool.get('ir.mail_server')                        
        for msg in msgs:
            #set email
            email_msg = ir_mail_server.build_email(msg['from'], msg['to'], msg['subject'], msg['body'],email_cc=msg['cc'], attachments=msg['attachments'], subtype=msg['subtype'])
            res_email = ir_mail_server.send_email(cr, uid, email_msg)
            if res_email:
                _logger.info('Email successfully sent to: %s, model:%s, ids:%s' %(msg['to'],msg['model'],msg['model_ids']))
                #update object inform_type
                self.pool.get(msg['model']).write(cr,uid,msg['model_ids'],{'inform_type':msg['inform_type_new']},context=context);
            else:
                _logger.warning('Failed to send email to: %s', msg['to'])                
    def _inform_po(self,cr,uid,context=None):
        po_obj = self.pool.get("purchase.order")   
        
        email_from = config['email_from']
        email_msgs = []
        approver_emails = self._get_group_cata_name_emails(cr,uid,"Purchase Requisition",'Manager',context)
        '''
        1.PO Order:inform_type 
            1):confirmed: waitting approval
            2):rejected
            3):approved
        '''
        #waitting for approval
        email_to = []
        email_cc = []
        email_subject = ""
        email_body = ""
        #get object ids, email subject & body, object creator emails
        obj_ids, email_subject, email_body, email_cc, email_attachments = self._get_body_subject(cr,uid,'purchase.order','1','po_wait_approval',context = context)
        if len(obj_ids) > 0:
            email_msgs.append({'from':email_from,'to':approver_emails,'subject':email_subject,'body':email_body,'cc':email_cc,'subtype':'html','attachments':email_attachments,
                           'model':'purchase.order','model_ids':obj_ids,'inform_type_new':''})
        
        #rejected
        email_to = []
        email_cc = []
        email_subject = ""
        email_body = ""
        #get object ids, email subject & body, object creator emails
        obj_ids, email_subject, email_body, email_to, email_attachments = self._get_body_subject(cr,uid,'purchase.order','2','po_rejected',context = context)
        if len(email_to) > 0:
            email_msgs.append({'from':email_from,'to':email_to,'subject':email_subject,'body':email_body,'cc':email_cc,'subtype':'html',
                           'model':'purchase.order','model_ids':obj_ids,'inform_type_new':''})
        #approved
        email_to = []
        email_cc = []
        email_subject = ""
        email_body = ""
        email_creators = []
        #get object ids, email subject & body, object creator emails
        obj_ids, email_subject, email_body, email_to, email_attachments = self._get_body_subject(cr,uid,'purchase.order','3','po_approved',context = context)
        if len(email_to) > 0:
            email_msgs.append({'from':email_from,'to':email_to,'subject':email_subject,'body':email_body,'cc':email_cc,'subtype':'html',
                           'model':'purchase.order','model_ids':obj_ids,'inform_type_new':''})
        
        '''
        1.PO Order Line:inform_type 
            1):confirmed: waitting approval
            2):rejected
        '''
        #waitting for approval
        email_to = []
        email_cc = []
        email_subject = ""
        email_body = ""
        #get object ids, email subject & body, object creator emails
        obj_ids, email_subject, email_body, email_cc, email_attachments = self._get_body_subject(cr,uid,'purchase.order.line','1','po_line_wait_approval',context = context)
        if obj_ids:
            email_msgs.append({'from':email_from,'to':approver_emails,'subject':email_subject,'body':email_body,'cc':email_cc,'subtype':'html',
                               'model':'purchase.order.line','model_ids':obj_ids,'inform_type_new':''})
        
        #rejected
        email_to = []
        email_cc = []
        email_subject = ""
        email_body = ""
        #get object ids, email subject & body, object creator emails
        obj_ids, email_subject, email_body, email_to, email_attachments = self._get_body_subject(cr,uid,'purchase.order.line','2','po_line_rejected',context = context)
        if len(email_to) > 0:
            email_msgs.append({'from':email_from,'to':email_to,'subject':email_subject,'body':email_body,'cc':email_cc,'subtype':'html',
                           'model':'purchase.order.line','model_ids':obj_ids,'inform_type_new':''})
        
        #send all emails at last
        self._send_emails(cr,uid,email_msgs,context)
        return True 

order_informer()  