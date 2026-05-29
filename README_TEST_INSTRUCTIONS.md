# Testing the Mosquito-Finder App Locally

The Apple cloud environment where this AI runs cannot connect directly to your physical iPhone over USB. To test the app on your own device, you'll need to pull the code from GitHub and build it in your local Xcode.

## Steps

1. **Open Terminal** on your Mac.
2. Navigate to your project folder:
   ```bash
   cd ~/Project/AppleProject/Mosquito-finder
   # (Or wherever you cloned the repo)
   ```
3. **Pull the latest changes** I just pushed:
   ```bash
   git fetch origin
   git pull origin main
   ```
4. **Open the project in Xcode**:
   ```bash
   open Mosquito-finder.xcodeproj
   ```
5. **Select your iPhone** as the target device in the top bar of Xcode.
6. Make sure your Developer Account is selected under **Signing & Capabilities** for the `Mosquito-finder` target.
7. Click the **Play button** (or `Cmd + R`) to build and run the app on your phone.

## How to Test the "Cheat Mode" (for Video Demo)
For the App Store review video, grab a piece of white paper and draw a solid, dark black dot on it (about 2-4 mm wide). Point the camera at it, and the app will instantly detect it as a mosquito thanks to the high-contrast fallback logic I added.
