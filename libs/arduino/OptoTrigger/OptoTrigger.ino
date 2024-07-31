// Script adapted from https://forum.arduino.cc/t/serial-input-basics-updated/382007
// Example 5 - Receive with start- and end-markers combined with parsing

#define LED_PIN 12
#define OPTO_PIN 10
const byte numChars = 32;
char receivedChars[numChars];
char tempChars[numChars];  // temporary array for use when parsing

// variables to hold the parsed data


int duration;

int intensity;
int frequency;

boolean newData = false;

//============

void setup() {
  pinMode(OPTO_PIN, OUTPUT);
  analogWrite(OPTO_PIN, 0);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  Serial.begin(9600);
}

//============

void loop() {
  recvWithStartEndMarkers();
  if (newData == true) {
    strcpy(tempChars, receivedChars);
    // this temporary copy is necessary to protect the original data
    //   because strtok() used in parseData() replaces the commas with \0
    parseData();
    showParsedData();
    newData = false;

    digitalWrite(LED_PIN, HIGH);

    if (frequency == 0) {
      Serial.println("ONOFF");
      analogWrite(OPTO_PIN, intensity);
      delay(duration);
      analogWrite(OPTO_PIN, 0);

    } else {
      long interval = (1000 / frequency) / 2;
      Serial.println("Blink");

      unsigned long start_time = millis();

      while (millis() - start_time <= duration) {
        delay(interval);
        analogWrite(OPTO_PIN, intensity);
        delay(interval);
        analogWrite(OPTO_PIN, 0);
      }

      Serial.println(millis() - start_time);
    }
  }

  digitalWrite(LED_PIN, LOW);
  analogWrite(OPTO_PIN, 0);
}

//============

void recvWithStartEndMarkers() {
  static boolean recvInProgress = false;
  static byte ndx = 0;
  char startMarker = '<';
  char endMarker = '>';
  char rc;

  while (Serial.available() > 0 && newData == false) {
    rc = Serial.read();

    if (recvInProgress == true) {
      if (rc != endMarker) {
        receivedChars[ndx] = rc;
        ndx++;
        if (ndx >= numChars) {
          ndx = numChars - 1;
        }
      } else {
        receivedChars[ndx] = '\0';  // terminate the string
        recvInProgress = false;
        ndx = 0;
        newData = true;
      }
    }

    else if (rc == startMarker) {
      recvInProgress = true;
    }
  }
}

//============

void parseData() {  // split the data into its parts

  char* strtokIndx;  // this is used by strtok() as an index

  strtokIndx = strtok(tempChars, ",");  // get the first part - the string
  duration = atoi(strtokIndx);

  strtokIndx = strtok(NULL, ",");  // this continues where the previous call left off
  intensity = atoi(strtokIndx);    // convert this part to an integer

  strtokIndx = strtok(NULL, ",");
  frequency = atof(strtokIndx);  // convert this part to a float
}

//============

void showParsedData() {
  Serial.print("Duration ");
  Serial.println(duration);
  Serial.print("Intensity ");
  Serial.println(intensity);
  Serial.print("Frequency ");
  Serial.println(frequency);
}
