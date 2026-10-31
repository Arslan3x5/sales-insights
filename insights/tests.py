import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Dataset
from .services import analyze, map_columns

HEADER = "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country\n"
ROW = "489434,85048,GLASS BALL,12,2009-12-01 07:45:00,6.95,13085.0,United Kingdom\n"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadTests(TestCase):
    def upload(self, name, content):
        f = SimpleUploadedFile(name, content.encode(), content_type="text/csv")
        return self.client.post(reverse("upload"), {"file": f})

    def test_maps_common_column_names(self):
        mapping = map_columns(["Invoice", "Customer ID", "InvoiceDate", "Price", "Quantity", "Description"])
        self.assertEqual(mapping["customer_id"], "Customer ID")
        self.assertEqual(mapping["invoice_date"], "InvoiceDate")

    def test_valid_csv_creates_dataset(self):
        response = self.upload("sales.csv", HEADER + ROW)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Dataset.objects.get().row_count, 1)

    def test_rejects_non_csv_file(self):
        response = self.upload("sales.txt", HEADER + ROW)
        self.assertContains(response, "Please upload a .csv file.")
        self.assertEqual(Dataset.objects.count(), 0)

    def test_rejects_missing_columns(self):
        response = self.upload("sales.csv", "Invoice,Country\n1,UK\n")
        self.assertContains(response, "Missing required columns")
        self.assertEqual(Dataset.objects.count(), 0)


CLEANING_CSV = HEADER + "\n".join([
    "1001,A1,WIDGET,2,2010-01-05 10:00:00,5.00,1,UK",
    "1001,A2,GADGET,1,2010-01-05 10:00:00,20.00,1,UK",
    "C1002,A1,WIDGET,-1,2010-01-06 10:00:00,5.00,1,UK",
    "1003,A3,BROKEN,-3,2010-01-07 10:00:00,0.00,,UK",
    "1004,POST,POSTAGE,1,2010-02-01 10:00:00,15.00,2,UK",
    "1005,A4,FREEBIE,1,2010-02-02 10:00:00,0.00,2,UK",
    "1006,A1,WIDGET,4,2010-02-03 10:00:00,5.00,,France",
    "1006,A1,WIDGET,4,2010-02-03 10:00:00,5.00,,France",
]) + "\n"


class AnalyzeTests(TestCase):
    def setUp(self):
        mapping = map_columns(
            ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
        )
        self.result = analyze(io.BytesIO(CLEANING_CSV.encode()), mapping)

    def test_cleaning_removes_each_kind_of_bad_row(self):
        steps = {s["label"]: s["rows"] for s in self.result["cleaning"]["steps"]}
        self.assertEqual(steps["Cancelled invoices (start with C)"], 1)
        self.assertEqual(steps["Zero or negative quantity"], 1)
        self.assertEqual(steps["Zero or negative price"], 1)
        self.assertEqual(steps["Non-product codes (postage, fees, adjustments)"], 1)
        self.assertEqual(steps["Exact duplicate rows"], 1)
        self.assertEqual(self.result["cleaning"]["clean_rows"], 3)

    def test_kpis_use_only_clean_rows(self):
        kpis = self.result["kpis"]
        self.assertEqual(kpis["revenue"], 50.0)
        self.assertEqual(kpis["orders"], 2)
        self.assertEqual(kpis["customers"], 1)
        self.assertEqual(kpis["cancelled_invoices"], 1)

    def test_monthly_and_top_products(self):
        self.assertEqual([m["month"] for m in self.result["monthly"]], ["2010-01", "2010-02"])
        self.assertEqual(self.result["top_products"][0]["name"], "WIDGET")