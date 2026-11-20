import 'package:ailoha_agent/ailoha_agent.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (kDebugMode) {
    await initAgent();
  }
  runApp(const SampleRecipesApp());
}
