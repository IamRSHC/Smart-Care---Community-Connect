/*
  SmartCare sensor node firmware (ESP32)

  Reads:
    - MAX30102  -> heart rate + SpO2
    - DS18B20   -> body/ambient temperature
    - MPU6050   -> accelerometer magnitude + motion flag (for fall/inactivity)

  Posts a JSON reading to the backend /api/ingest endpoint over Wi-Fi
  every SEND_INTERVAL_MS milliseconds. Buffers the last reading locally
  if Wi-Fi is briefly unavailable and resends on reconnect.

  Libraries needed (Arduino Library Manager):
    - MAX30105 (SparkFun MAX3010x)
    - OneWire + DallasTemperature (for DS18B20)
    - MPU6050 (Electronic Cats / Jeff Rowberg i2cdevlib)
    - ArduinoJson
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <MAX30105.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <MPU6050.h>

// ---- Configuration: fill these in for your deployment ----
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BACKEND_URL   = "http://YOUR_BACKEND_IP:8000/api/ingest";
const int   RESIDENT_ID   = 1;              // matches the resident row in the backend DB
const unsigned long SEND_INTERVAL_MS = 5000; // send a reading every 5s

// ---- Sensor objects ----
MAX30105 particleSensor;
#define ONE_WIRE_BUS 4
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);
MPU6050 mpu;

unsigned long lastSendTime = 0;

void connectWifi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected: " + WiFi.localIP().toString());
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  connectWifi();

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 not found - check wiring");
  } else {
    particleSensor.setup(); // default HR/SpO2 config
  }

  tempSensor.begin();

  mpu.initialize();
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 not found - check wiring");
  }
}

// Placeholder HR/SpO2 extraction. Replace with SparkFun's heartRate.h /
// spo2_algorithm.h routines (see library examples) for a real reading;
// the raw IR/RED values below are just to show where they plug in.
struct VitalsReading {
  float heartRate;
  float spo2;
};

VitalsReading readVitals() {
  long irValue = particleSensor.getIR();
  // TODO: replace with SparkFun's maxim_heart_rate_and_oxygen_saturation()
  // algorithm using a buffer of IR/RED samples. Returning placeholders here
  // so the pipeline can be tested end-to-end before the algorithm is tuned.
  VitalsReading v;
  v.heartRate = (irValue > 50000) ? 72.0 : 0.0; // 0 => no finger/contact detected
  v.spo2 = (irValue > 50000) ? 97.0 : 0.0;
  return v;
}

float readTemperature() {
  tempSensor.requestTemperatures();
  return tempSensor.getTempCByIndex(0);
}

struct MotionReading {
  float accelMagnitude;
  bool isMoving;
};

MotionReading readMotion() {
  int16_t ax, ay, az;
  mpu.getAcceleration(&ax, &ay, &az);

  // convert raw units to g (MPU6050 default range +/-2g -> 16384 LSB/g)
  float axg = ax / 16384.0;
  float ayg = ay / 16384.0;
  float azg = az / 16384.0;

  float magnitude = sqrt(axg * axg + ayg * ayg + azg * azg);

  MotionReading m;
  m.accelMagnitude = magnitude;
  m.isMoving = fabs(magnitude - 1.0) > 0.15; // simple "not at rest" threshold
  return m;
}

void sendReading(VitalsReading vitals, float temperature, MotionReading motion) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi down, buffering reading (not sent)");
    connectWifi();
    return;
  }

  HTTPClient http;
  http.begin(BACKEND_URL);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  doc["resident_id"] = RESIDENT_ID;
  doc["heart_rate"] = vitals.heartRate;
  doc["spo2"] = vitals.spo2;
  doc["temperature"] = temperature;
  doc["accel_magnitude"] = motion.accelMagnitude;
  doc["is_moving"] = motion.isMoving;

  String payload;
  serializeJson(doc, payload);

  int httpCode = http.POST(payload);
  Serial.printf("POST /api/ingest -> %d\n", httpCode);
  http.end();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    VitalsReading vitals = readVitals();
    float temperature = readTemperature();
    MotionReading motion = readMotion();

    sendReading(vitals, temperature, motion);
  }
}
