#include <Streaming.h>

const int triggerPin =  9;// the number of the camera pin

int triggerState = LOW; // triggerState used to set the camera trigger

unsigned long previousMicros = 0; // will store last time triggerPin was updated

unsigned long interval = 0; // interval at which to blink (milliseconds)

void setup() {
  // set the digital pin as output:
  pinMode(triggerPin, OUTPUT);
  digitalWrite(triggerPin, LOW);
  Serial.begin(9600);
}


void loop() {
  
  unsigned long currentMicros = micros();
  
  if (Serial.available() > 0){
    interval = Serial.parseInt();
    Serial << "Triggering camera(s) at " << interval << " Hz" << endl;
    interval = 1000000/interval/2; // In Microseconds
    
  }
  
  if (interval == 0) {
    return; 
  }
  
  if (currentMicros - previousMicros >= interval) {
    // save the last time you blinked the trigger
    previousMicros = currentMicros;

    // if the trigger is off turn it on and vice-versa:
    if (triggerState == LOW) {
      triggerState = HIGH;
    } else {
      triggerState = LOW;
    }

    // set the trigger with the triggerState of the variable:
    digitalWrite(triggerPin, triggerState);
  }
}
