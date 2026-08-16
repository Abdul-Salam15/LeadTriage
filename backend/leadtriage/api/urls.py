from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("leads/upload", views.leads_upload, name="leads-upload"),
    path("jobs/<str:job_id>", views.job_detail, name="job-detail"),
    path("jobs/<str:job_id>/mapping", views.confirm_mapping, name="confirm-mapping"),
    path("jobs/<str:job_id>/process", views.process_job, name="process-job"),
    path("jobs/<str:job_id>/results", views.job_results, name="job-results"),
    path("jobs/<str:job_id>/leads", views.leads_list, name="leads-list"),
    path("jobs/<str:job_id>/leads/<str:lead_id>", views.lead_detail, name="lead-detail"),
    path("jobs/<str:job_id>/leads/<str:lead_id>/status", views.lead_status, name="lead-status"),
    path("jobs/<str:job_id>/leads/<str:lead_id>/override", views.lead_override, name="lead-override"),
    path("jobs/<str:job_id>/lead-status", views.lead_statuses, name="lead-statuses"),
    path("jobs/<str:job_id>/lead-overrides", views.lead_overrides, name="lead-overrides"),
    path("jobs/<str:job_id>/clusters", views.clusters_list, name="clusters-list"),
    path("jobs/<str:job_id>/clusters/<str:cluster_id>", views.cluster_detail, name="cluster-detail"),
    path("jobs/<str:job_id>/export/csv", views.export_csv, name="export-csv"),
    path("jobs/<str:job_id>/export/json", views.export_json, name="export-json"),
]
