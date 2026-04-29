// -------- PINS --------
const int ENA = 10; 
const int IN1 = 9;  
const int IN2 = 8;  
const int IN3 = 7;  
const int IN4 = 6;  
const int ENB = 5;  

const int augerDir1 = 2;   
const int augerDir2 = 3;   
const int augerEnable = 4; 

const int trigPin = 11;
const int echoPin = 12;
const int buzzerPin = 16;

char command;
long duration;
int distance = 400;

unsigned long lastPingTime = 0;
unsigned long beepTimer = 0;
unsigned long lastTelemetryTime = 0;
bool isBeeping = false;
bool manualBuzzer = false;

bool augerPulsing = false;
unsigned long augerPulseTimer = 0;
bool pulseHigh = false; 

void setup() {
  Serial.begin(9600);

  pinMode(ENA, OUTPUT); pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT); pinMode(ENB, OUTPUT);
  pinMode(augerDir1, OUTPUT); pinMode(augerDir2, OUTPUT); pinMode(augerEnable, OUTPUT);
  pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT); pinMode(buzzerPin, OUTPUT);

  digitalWrite(buzzerPin, LOW); 
  stopRobot();
  stopAuger(); 
}

void loop() {
  // 1. SENSOR
  if (millis() - lastPingTime > 50) {
    lastPingTime = millis();
    distance = getDistance();
  }

  // 2. TELEMETRY
  if (millis() - lastTelemetryTime > 250) {
    lastTelemetryTime = millis();
    Serial.print("D:"); Serial.println(distance);
  }

  // 3. BUZZER
  if (manualBuzzer) {
    digitalWrite(buzzerPin, HIGH); 
  } else {
    if (distance > 22 && distance < 60) {
      int waitTime = map(distance, 25, 60, 50, 400); 
      if (!isBeeping && (millis() - beepTimer > waitTime)) {
        digitalWrite(buzzerPin, HIGH);
        isBeeping = true; beepTimer = millis(); 
      } else if (isBeeping && (millis() - beepTimer > 50)) {
        digitalWrite(buzzerPin, LOW);
        isBeeping = false; beepTimer = millis(); 
      }
    } else {
      digitalWrite(buzzerPin, LOW); isBeeping = false;
    }
  }

  // 4. PULSE AUGER
  if (augerPulsing) {
    if (pulseHigh && (millis() - augerPulseTimer > 80)) { 
      digitalWrite(augerEnable, LOW);
      pulseHigh = false; augerPulseTimer = millis();
    } else if (!pulseHigh && (millis() - augerPulseTimer > 40)) { 
      digitalWrite(augerEnable, HIGH);
      pulseHigh = true; augerPulseTimer = millis();
    }
  }

  // 5. READ COMMANDS
  if (Serial.available()) {
    command = Serial.read();
    if (command == '\n' || command == '\r' || command == ' ') return; 

    switch (command) {
      case 'F': forward(); break;
      case 'B': backward(); break;
      case 'L': left(); break;
      case 'R': right(); break;
      case 'S': stopRobot(); break;

      case 'X': startAuger(); break;   
      case 'x': stopAuger(); break;    
      case 'P': startPulseAuger(); break; 

      case 'Z': manualBuzzer = true; break;  
      case 'z': manualBuzzer = false; break; 
    }
  }
}

int getDistance() {
  digitalWrite(trigPin, LOW); delayMicroseconds(5);
  digitalWrite(trigPin, HIGH); delayMicroseconds(20); 
  digitalWrite(trigPin, LOW);
  duration = pulseIn(echoPin, HIGH, 30000); 
  if (duration == 0) return 400; 
  int d = duration * 0.034 / 2;
  if (d < 22) return 400; 
  return d;
}

void startAuger() {
  augerPulsing = false; 
  digitalWrite(augerDir1, HIGH); digitalWrite(augerDir2, LOW);
  digitalWrite(augerEnable, HIGH); 
}

void startPulseAuger() {
  if (!augerPulsing) {
    augerPulsing = true; pulseHigh = true; augerPulseTimer = millis();
    digitalWrite(augerDir1, HIGH); digitalWrite(augerDir2, LOW);
    digitalWrite(augerEnable, HIGH); 
  }
}

void stopAuger() {
  augerPulsing = false; 
  digitalWrite(augerEnable, LOW); digitalWrite(augerDir1, LOW); digitalWrite(augerDir2, LOW);
}

void forward() {
  analogWrite(ENA, 255); digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  analogWrite(ENB, 255); digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
}
void backward() {
  analogWrite(ENA, 255); digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);
  analogWrite(ENB, 255); digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
}
void left() {
  analogWrite(ENA, 255); digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);
  analogWrite(ENB, 255); digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
}
void right() {
  analogWrite(ENA, 255); digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  analogWrite(ENB, 255); digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
}
void stopRobot() {
  analogWrite(ENA, 0); analogWrite(ENB, 0);
}