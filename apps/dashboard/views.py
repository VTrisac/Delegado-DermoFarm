from django.shortcuts import render

def dashboard_view(request):
    context = {
        "total_conversations": 120,
        "active_agents": 15,
        "messages_today": 300
    }
    return render(request, "dashboard/dashboard.html", context)

