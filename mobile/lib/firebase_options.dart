// Firebase client configuration, taken from android/app/google-services.json.
// These values identify the app to Firebase and are shipped inside every APK; they are
// not secrets. The server-side key (service account) stays on the server only.
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';

class DefaultFirebaseOptions {
  /// Null on platforms that are not configured yet (iOS needs GoogleService-Info / APNs first).
  static FirebaseOptions? get currentPlatform =>
      defaultTargetPlatform == TargetPlatform.android ? android : null;

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyB1ur5kviewTwNrDTGSvIE_uDgrRLq10Cw',
    appId: '1:981654644318:android:25d68059de0061c635b6cf',
    messagingSenderId: '981654644318',
    projectId: 'nalut-university',
    storageBucket: 'nalut-university.firebasestorage.app',
  );
}
