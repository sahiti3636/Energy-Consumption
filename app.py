from flask import Flask, render_template, jsonify, url_for
from pymongo import MongoClient
import pandas as pd
import google.generativeai as genai
import os
from datetime import datetime

# Configure Gemini API
key = "AIzaSyDYoa4ID8dzXRpMh6bOpisqdDx_sjiAOA4"  # Replace with your key
genai.configure(api_key=key)

app = Flask(__name__)

# MongoDB connection
client = MongoClient("mongodb+srv://Cluster65166:c0FecmZsY35x@cluster65166.k7gqdhi.mongodb.net/")
db = client["energy-consumption"]
collection = db["energy-consumption"]

def load_data():
    data = list(collection.find({}, {"_id": 0}))
    df = pd.DataFrame(data)
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df.sort_values('Datetime', inplace=True)
    return df

@app.route("/")
def index():
    return render_template("app.html")

@app.route("/summary")
def summary():
    df = load_data()
    df['Hour'] = df['Datetime'].dt.hour
    hourly = df.groupby('Hour')['Global_active_power'].mean()
    avg = hourly.mean()
    peak_hour = hourly.idxmax()
    peak_val = hourly.max()
    percent = round((peak_val - avg) / avg * 100, 1)

    return render_template("summary.html", 
                         peak_hour=peak_hour,
                         peak_val=round(peak_val, 2),
                         avg_val=round(avg, 2),
                         percent=percent,
                         hourly=hourly.to_dict())

@app.route("/balancing")
def balancing():
    df = load_data()
    df['Hour'] = df['Datetime'].dt.hour
    hourly = df.groupby('Hour')['Global_active_power'].mean().round(2)

    def label(val): return "✅ OK" if val < 4.0 else "⚠️ High Load"
    actions = [label(val) for val in hourly]

    table_data = list(zip(hourly.index.tolist(), hourly.tolist(), actions))
    return render_template("balancing.html", table=table_data)

@app.route("/scheduling")
def scheduling():
    df = load_data()
    df['Hour'] = df['Datetime'].dt.hour
    hourly = df.groupby('Hour')['Global_active_power'].mean().round(2)

    # Calculate peak and off-peak hours
    peak_threshold = hourly.quantile(0.7)
    low_threshold = hourly.quantile(0.3)

    peak_hours = hourly[hourly >= peak_threshold].index.tolist()
    low_load_hours = hourly[hourly <= low_threshold].index.tolist()
    medium_hours = hourly[(hourly > low_threshold) & (hourly < peak_threshold)].index.tolist()

    # Prepare data for Gemini analysis
    hourly_data = {
        "hourly_consumption": hourly.to_dict(),
        "peak_hours": peak_hours,
        "low_load_hours": low_load_hours,
        "average_consumption": hourly.mean(),
        "peak_consumption": hourly.max(),
        "current_time": datetime.now().strftime("%H:%M")
    }

    # Get AI recommendations
    ai_recommendations = get_ai_grid_recommendations(hourly_data)

    # Grid management strategies
    grid_strategies = [
        {
            "Strategy": "Standby Generator Dispatch",
            "Type": "Peak Management",
            "Peak Hours": peak_hours,
            "Action": "Deploy backup generators",
            "AI_Recommendation": ai_recommendations.get("generator_dispatch", "Deploy during peak hours"),
            "Priority": "High" if len(peak_hours) > 6 else "Medium"
        },
        {
            "Strategy": "Battery Storage Charging",
            "Type": "Energy Storage",
            "Optimal Hours": low_load_hours,
            "Action": "Charge battery systems",
            "AI_Recommendation": ai_recommendations.get("battery_charging", "Charge during low-demand periods"),
            "Priority": "High"
        },
        {
            "Strategy": "Renewable Energy Allocation",
            "Type": "Clean Energy",
            "Best Hours": medium_hours + low_load_hours,
            "Action": "Maximize renewable usage",
            "AI_Recommendation": ai_recommendations.get("renewable_allocation", "Optimize solar/wind integration"),
            "Priority": "Medium"
        },
        {
            "Strategy": "Demand Response Program",
            "Type": "Load Management",
            "Target Hours": peak_hours,
            "Action": "Reduce non-critical loads",
            "AI_Recommendation": ai_recommendations.get("demand_response", "Implement load shedding protocols"),
            "Priority": "High" if hourly.max() > 5.0 else "Medium"
        }
    ]

    # Real-time grid status
    current_hour = datetime.now().hour
    current_load = hourly.get(current_hour, 0)

    if current_hour in peak_hours:
        grid_status = "⚠️ Peak Load Period"
        status_color = "red"
    elif current_hour in low_load_hours:
        grid_status = "✅ Low Load Period"
        status_color = "green"
    else:
        grid_status = "🔄 Medium Load Period"
        status_color = "orange"

    return render_template("scheduling.html",
                         strategies=grid_strategies,
                         hourly_data=hourly.to_dict(),
                         peak_hours=peak_hours,
                         low_load_hours=low_load_hours,
                         current_load=round(current_load, 2),
                         grid_status=grid_status,
                         status_color=status_color,
                         ai_insights=ai_recommendations.get("general_insights", "AI analysis complete"))

def get_ai_grid_recommendations(hourly_data):
    """Get AI-powered grid management recommendations using Google Gemini"""
    try:
        model = genai.GenerativeModel('models/gemini-pro')

        prompt = f"""
        As a smart grid energy management expert, analyze this hourly energy consumption data and provide specific recommendations for grid operators:

        Hourly Consumption Data (kW): {hourly_data['hourly_consumption']}
        Peak Hours: {hourly_data['peak_hours']}
        Low Load Hours: {hourly_data['low_load_hours']}
        Average Consumption: {hourly_data['average_consumption']:.2f} kW
        Peak Consumption: {hourly_data['peak_consumption']:.2f} kW
        Current Time: {hourly_data['current_time']}

        Provide concise recommendations for:
        1. Generator Dispatch Strategy (when to deploy standby generators)
        2. Battery Charging Schedule (optimal hours for energy storage)
        3. Renewable Energy Allocation (best times for solar/wind integration)
        4. Demand Response Actions (load management during peaks)
        5. General Grid Management Insights

        Format as brief, actionable recommendations (max 50 words each).
        """

        response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
        max_output_tokens=200,
        temperature=0.3)
        )


        ai_response = response.text

        # Parse the response into structured recommendations
        recommendations = {
            "generator_dispatch": extract_recommendation(ai_response, "Generator Dispatch Strategy", "Deploy generators during hours with high peak load."),
            "battery_charging": extract_recommendation(ai_response, "Battery Charging Schedule", "Charge batteries during low-demand hours (e.g., 0-6 AM)."),
            "renewable_allocation": extract_recommendation(ai_response, "Renewable Energy Allocation", "Maximize solar during daylight hours, wind during off-peak and windy periods."),
            "demand_response": extract_recommendation(ai_response, "Demand Response Actions", "Implement load shedding protocols during critical peak hours."),
            "general_insights": extract_recommendation(ai_response, "General Grid Management Insights", "Optimize load distribution across the 24-hour cycle and leverage storage.")
        }

        return recommendations

    except Exception as e:
        print(f"Gemini API Error: {e}")
        # Fallback recommendations if API fails
        return {
            "generator_dispatch": "Deploy backup generators during peak consumption hours",
            "battery_charging": "Schedule charging during low-demand periods (typically 1-5 AM)",
            "renewable_allocation": "Maximize renewable integration during moderate load hours",
            "demand_response": "Implement demand response programs during peak hours",
            "general_insights": "Balance load distribution and optimize renewable energy usage"
        }

def extract_recommendation(text, keyword, fallback):
    """Extract specific recommendation from AI response by looking for keywords followed by the recommendation."""
    lines = text.split('\n')
    for line in lines:
        if keyword.lower() in line.lower():
            parts = line.split(keyword, 1)
            if len(parts) > 1:
                return parts[1].strip(':- ').strip()
    return fallback


if __name__ == "__main__":
    # This block only runs when you run app.py directly (e.g., for local development)
    # App Engine will use the 'entrypoint' from app.yaml with gunicorn
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8081)))

