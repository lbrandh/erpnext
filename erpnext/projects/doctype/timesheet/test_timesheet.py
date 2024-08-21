# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import datetime
import unittest

import frappe
from frappe.model.mapper import make_mapped_doc
from frappe.utils import add_to_date, now_datetime, nowdate

from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.projects.doctype.timesheet.timesheet import OverlapError, make_sales_invoice
from erpnext.setup.doctype.employee.test_employee import make_employee


class TestTimesheet(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("Timesheet")

	def test_timesheet_billing_amount(self):
		emp = make_employee("test_employee_6@salary.com")
		timesheet = make_timesheet(emp, simulate=True, is_billable=1)

		self.assertEqual(timesheet.total_hours, 2)
		self.assertEqual(timesheet.total_billable_hours, 2)
		self.assertEqual(timesheet.time_logs[0].billing_rate, 50)
		self.assertEqual(timesheet.time_logs[0].billing_amount, 100)
		self.assertEqual(timesheet.total_billable_amount, 100)

	def test_timesheet_billing_amount_not_billable(self):
		emp = make_employee("test_employee_6@salary.com")
		timesheet = make_timesheet(emp, simulate=True, is_billable=0)

		self.assertEqual(timesheet.total_hours, 2)
		self.assertEqual(timesheet.total_billable_hours, 0)
		self.assertEqual(timesheet.time_logs[0].billing_rate, 0)
		self.assertEqual(timesheet.time_logs[0].billing_amount, 0)
		self.assertEqual(timesheet.total_billable_amount, 0)

	def test_sales_invoice_from_timesheet(self):
		emp = make_employee("test_employee_6@salary.com")

		timesheet = make_timesheet(emp, simulate=True, is_billable=1)
		sales_invoice = make_sales_invoice(timesheet.name, "_Test Item", "_Test Customer", currency="INR")
		sales_invoice.due_date = nowdate()
		sales_invoice.submit()
		timesheet = frappe.get_doc("Timesheet", timesheet.name)
		self.assertEqual(sales_invoice.total_billing_amount, 100)
		self.assertEqual(timesheet.status, "Billed")
		self.assertEqual(sales_invoice.customer, "_Test Customer")

		item = sales_invoice.items[0]
		self.assertEqual(item.item_code, "_Test Item")
		self.assertEqual(item.qty, 2.00)
		self.assertEqual(item.rate, 50.00)

	def test_timesheet_billing_based_on_project(self):
		emp = make_employee("test_employee_6@salary.com")
		project = frappe.get_value("Project", {"project_name": "_Test Project"})

		timesheet = make_timesheet(
			emp, simulate=True, is_billable=1, project=project, company="_Test Company"
		)
		sales_invoice = create_sales_invoice(do_not_save=True)
		sales_invoice.project = project
		sales_invoice.submit()

		ts = frappe.get_doc("Timesheet", timesheet.name)
		self.assertEqual(ts.per_billed, 100)
		self.assertEqual(ts.time_logs[0].sales_invoice, sales_invoice.name)

	def test_timesheet_time_overlap(self):
		emp = make_employee("test_employee_6@salary.com")

		settings = frappe.get_single("Projects Settings")
		initial_setting = settings.ignore_employee_time_overlap
		settings.ignore_employee_time_overlap = 0
		settings.save()

		update_activity_type("_Test Activity Type")
		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = emp
		timesheet.append(
			"time_logs",
			{
				"billable": 1,
				"activity_type": "_Test Activity Type",
				"from_time": now_datetime(),
				"to_time": now_datetime() + datetime.timedelta(hours=3),
				"company": "_Test Company",
			},
		)
		timesheet.append(
			"time_logs",
			{
				"billable": 1,
				"activity_type": "_Test Activity Type",
				"from_time": now_datetime(),
				"to_time": now_datetime() + datetime.timedelta(hours=3),
				"company": "_Test Company",
			},
		)

		self.assertRaises(frappe.ValidationError, timesheet.save)

		settings.ignore_employee_time_overlap = 1
		settings.save()
		timesheet.save()  # should not throw an error

		settings.ignore_employee_time_overlap = initial_setting
		settings.save()

	def test_timesheet_not_overlapping_with_continuous_timelogs(self):
		emp = make_employee("test_employee_6@salary.com")

		update_activity_type("_Test Activity Type")
		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = emp
		timesheet.append(
			"time_logs",
			{
				"billable": 1,
				"activity_type": "_Test Activity Type",
				"from_time": now_datetime(),
				"to_time": now_datetime() + datetime.timedelta(hours=3),
				"company": "_Test Company",
			},
		)
		timesheet.append(
			"time_logs",
			{
				"billable": 1,
				"activity_type": "_Test Activity Type",
				"from_time": now_datetime() + datetime.timedelta(hours=3),
				"to_time": now_datetime() + datetime.timedelta(hours=4),
				"company": "_Test Company",
			},
		)

		timesheet.save()  # should not throw an error

	def test_to_time(self):
		emp = make_employee("test_employee_6@salary.com")
		from_time = now_datetime()

		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = emp
		timesheet.append(
			"time_logs",
			{
				"billable": 1,
				"activity_type": "_Test Activity Type",
				"from_time": from_time,
				"hours": 2,
				"company": "_Test Company",
			},
		)
		timesheet.save()

		to_time = timesheet.time_logs[0].to_time
		self.assertEqual(to_time, add_to_date(from_time, hours=2, as_datetime=True))

	def test_per_billed_hours(self):
		"""If amounts are 0, per_billed should be calculated based on hours."""
		ts = frappe.new_doc("Timesheet")
		ts.total_billable_amount = 0
		ts.total_billed_amount = 0
		ts.total_billable_hours = 2

		ts.total_billed_hours = 0.5
		ts.calculate_percentage_billed()
		self.assertEqual(ts.per_billed, 25)

		ts.total_billed_hours = 2
		ts.calculate_percentage_billed()
		self.assertEqual(ts.per_billed, 100)

	def test_per_billed_amount(self):
		"""If amounts are > 0, per_billed should be calculated based on amounts, regardless of hours."""
		ts = frappe.new_doc("Timesheet")
		ts.total_billable_hours = 2
		ts.total_billed_hours = 1
		ts.total_billable_amount = 200
		ts.total_billed_amount = 50
		ts.calculate_percentage_billed()
		self.assertEqual(ts.per_billed, 25)

		ts.total_billed_hours = 3
		ts.total_billable_amount = 200
		ts.total_billed_amount = 200
		ts.calculate_percentage_billed()
		self.assertEqual(ts.per_billed, 100)

	def test_timesheet_create_timesheet_from_project(self):
		project_name = "_Test Project_Timesheet from Project"

		# Reset
		if frappe.db.exists("Project", {"project_name": project_name}):
			deletable_project = frappe.get_doc("Project", {"project_name": project_name})
			frappe.db.sql(""" delete from tabTask where project = %s """, deletable_project.name)
			frappe.delete_doc("Project", deletable_project.name)

		# Create base project for test
		project = frappe.get_doc(
			dict(
				doctype="Project",
				project_name=project_name,
				status="Open",
				expected_start_date=nowdate(),
				company="_Test Company",
			)
		).insert()

		# Create timesheet from project
		made_timesheet = make_mapped_doc(
			"erpnext.projects.doctype.project.project.make_timesheet", project.name
		)
		self.assertEqual(made_timesheet.doctype, "Timesheet")
		self.assertEqual(made_timesheet.parent_project, project.name)
		self.assertEqual(made_timesheet.customer, None)
		self.assertEqual(made_timesheet.time_logs[0].project, project.name)
		self.assertEqual(made_timesheet.time_logs[0].task, None)
		self.assertEqual(made_timesheet.time_logs[0].expected_hours, 0.0)

	def test_timesheet_create_timesheet_from_project_with_customer(self):
		project_name = "_Test Project_Timesheet from Project w Customer"
		customer_name = "_Test Customer_Timesheet from Project w Customer"

		if frappe.db.exists("Project", {"project_name": project_name}):
			deletable_project = frappe.get_doc("Project", {"project_name": project_name})
			frappe.db.sql(""" delete from tabTask where project = %s """, deletable_project.name)
			frappe.delete_doc("Project", deletable_project.name)

		# Create customer
		customer = frappe.get_doc(
			dict(
				doctype="Customer",
				customer_name=customer_name,
				company="_Test Company",
			)
		).insert()

		# Create project with customer
		project = frappe.get_doc(
			dict(
				doctype="Project",
				project_name=project_name,
				status="Open",
				expected_start_date=nowdate(),
				company="_Test Company",
				customer=customer,
			)
		).insert()

		# Create timesheet from project
		made_timesheet = make_mapped_doc(
			"erpnext.projects.doctype.project.project.make_timesheet", project.name
		)
		self.assertEqual(made_timesheet.doctype, "Timesheet")
		self.assertEqual(made_timesheet.parent_project, project.name)
		self.assertEqual(made_timesheet.customer, customer.name)
		self.assertEqual(made_timesheet.time_logs[0].project, project.name)
		self.assertEqual(made_timesheet.time_logs[0].task, None)
		self.assertEqual(made_timesheet.time_logs[0].expected_hours, 0.0)

	def test_timesheet_create_timesheet_from_task(self):
		project_name = "_Test Project_Timesheet from Task"
		task_name = "_Test Task_Timesheet from Task"

		# Reset
		if frappe.db.exists("Project", {"project_name": project_name}):
			deletable_project = frappe.get_doc("Project", {"project_name": project_name})
			frappe.db.sql(""" delete from tabTask where project = %s """, deletable_project.name)
			frappe.delete_doc("Project", deletable_project.name)

		# Create base project for test
		project = frappe.get_doc(
			dict(
				doctype="Project",
				project_name=project_name,
				status="Open",
				expected_start_date=nowdate(),
				company="_Test Company",
			)
		).insert()

		# Create base task for test
		task = frappe.get_doc(
			dict(
				doctype="Task",
				subject=task_name,
				project=project.name,
				status="Open",
				expected_hours=120.0,
			)
		).insert()

		# Create timesheet from project
		made_timesheet = make_mapped_doc("erpnext.projects.doctype.task.task.make_timesheet", task.name)
		self.assertEqual(made_timesheet.doctype, "Timesheet")
		self.assertEqual(made_timesheet.parent_project, project.name)
		self.assertEqual(made_timesheet.customer, None)
		self.assertEqual(made_timesheet.time_logs[0].project, project.name)
		self.assertEqual(made_timesheet.time_logs[0].task, task.name)
		self.assertEqual(made_timesheet.time_logs[0].expected_hours, 120.0)

	def test_timesheet_create_timesheet_from_task_with_customer(self):
		project_name = "_Test Project_Timesheet from Task w Customer"
		task_name = "_Test Task_Timesheet from Task w Customer"
		customer_name = "_Test Customer_Timesheet from Task w Customer"

		if frappe.db.exists("Project", {"project_name": project_name}):
			deletable_project = frappe.get_doc("Project", {"project_name": project_name})
			frappe.db.sql(""" delete from tabTask where project = %s """, deletable_project.name)
			frappe.delete_doc("Project", deletable_project.name)

		# Create customer
		customer = frappe.get_doc(
			dict(
				doctype="Customer",
				customer_name=customer_name,
				company="_Test Company",
			)
		).insert()

		# Create project with customer
		project = frappe.get_doc(
			dict(
				doctype="Project",
				project_name=project_name,
				status="Open",
				expected_start_date=nowdate(),
				company="_Test Company",
				customer=customer,
			)
		).insert()

		# Create base task for test
		task = frappe.get_doc(
			dict(
				doctype="Task",
				subject=task_name,
				project=project.name,
				status="Open",
				expected_hours=120.0,
			)
		).insert()

		# Create timesheet from project
		made_timesheet = make_mapped_doc("erpnext.projects.doctype.task.task.make_timesheet", task.name)
		self.assertEqual(made_timesheet.doctype, "Timesheet")
		self.assertEqual(made_timesheet.parent_project, project.name)
		self.assertEqual(made_timesheet.customer, customer.name)
		self.assertEqual(made_timesheet.time_logs[0].project, project.name)
		self.assertEqual(made_timesheet.time_logs[0].task, task.name)
		self.assertEqual(made_timesheet.time_logs[0].expected_hours, 120.0)


def make_timesheet(
	employee,
	simulate=False,
	is_billable=0,
	activity_type="_Test Activity Type",
	project=None,
	task=None,
	company=None,
):
	update_activity_type(activity_type)
	timesheet = frappe.new_doc("Timesheet")
	timesheet.employee = employee
	timesheet.company = company or "_Test Company"
	timesheet_detail = timesheet.append("time_logs", {})
	timesheet_detail.is_billable = is_billable
	timesheet_detail.activity_type = activity_type
	timesheet_detail.from_time = now_datetime()
	timesheet_detail.hours = 2
	timesheet_detail.to_time = timesheet_detail.from_time + datetime.timedelta(hours=timesheet_detail.hours)
	timesheet_detail.project = project
	timesheet_detail.task = task

	for data in timesheet.get("time_logs"):
		if simulate:
			while True:
				try:
					timesheet.save(ignore_permissions=True)
					break
				except OverlapError:
					data.from_time = data.from_time + datetime.timedelta(minutes=10)
					data.to_time = data.from_time + datetime.timedelta(hours=data.hours)
		else:
			timesheet.save(ignore_permissions=True)

	timesheet.submit()

	return timesheet


def update_activity_type(activity_type):
	activity_type = frappe.get_doc("Activity Type", activity_type)
	activity_type.billing_rate = 50.0
	activity_type.save(ignore_permissions=True)
