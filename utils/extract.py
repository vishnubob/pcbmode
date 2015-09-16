#!/usr/bin/python

import os
import json

import config
import messages as msg

# pcbmode modules
import utils
from point import Point



def extract():
    """
    """

    svg_in = utils.openBoardSVG()

    msg.info("Extracting routing and vias")
    extractRouting(svg_in)

    msg.info("Extracting components info")
    extractComponents(svg_in)

    msg.info("Extracting documentation and indicies locations")
    extractDocs(svg_in)

    return




def extractComponents(svg_in):
    """
    """
    
    # Get copper refdef shape groups from SVG data

    xpath_expr_place = '//svg:g[@pcbmode:pcb-layer="%s"]//svg:g[@pcbmode:sheet="placement"]//svg:g[@pcbmode:type="%s"]'

    xpath_expr_copper_pads = '//svg:g[@pcbmode:pcb-layer="%s"]//svg:g[@pcbmode:sheet="copper"]//svg:g[@pcbmode:sheet="pads"]//svg:g[@pcbmode:refdef]'

    xpath_expr_refdefs = '//svg:g[@pcbmode:pcb-layer="%s"]//svg:g[@pcbmode:sheet="silkscreen"]//svg:g[@pcbmode:type="refdef"][@pcbmode:refdef="%s"]'


    for pcb_layer in config.stk['surface-layer-names']:
        
        # Find all 'component' markers
        markers = svg_in.findall(xpath_expr_place % (pcb_layer, 'component'), 
                                 namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                             'svg':config.cfg['ns']['svg']})
        # Find all 'shape' markers
        markers += svg_in.findall(xpath_expr_place % (pcb_layer, 'shape'), 
                                  namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                              'svg':config.cfg['ns']['svg']})

        for marker in markers:

            transform_data = utils.parseTransform(marker.get('transform'))
            refdef = marker.get('{'+config.cfg['ns']['pcbmode']+'}refdef')
            marker_type = marker.get('{'+config.cfg['ns']['pcbmode']+'}type')
            
            if marker_type == 'component':
                comp_dict = config.brd['components'][refdef]
            else:
                comp_dict = config.brd['shapes'][refdef]

            new_location = transform_data['location']
            old_location = utils.toPoint(comp_dict.get('location') or [0, 0])

            # Invert 'y' coordinate
            new_location.y *= config.cfg['invert-y']

            # Change component location if needed
            if new_location != old_location:
                x1 = utils.niceFloat(old_location.x)
                y1 = utils.niceFloat(old_location.y)
                x2 = utils.niceFloat(new_location.x)
                y2 = utils.niceFloat(new_location.y)
                msg.subInfo("%s has moved from [%s,%s] to [%s,%s]" % (refdef,x1,y2,x2,y2))
                comp_dict['location'] = [x2,y2]

            # Change component rotation if needed
            if transform_data['type'] == 'matrix':
                old_rotate = comp_dict.get('rotate') or 0
                new_rotate = transform_data['rotate']
                comp_dict['rotate'] = utils.niceFloat((old_rotate+new_rotate) % 360)
                msg.subInfo("Component %s rotated from %s to %s" % (refdef, 
                                                                    old_rotate, 
                                                                    comp_dict['rotate']))


            refdef_texts = svg_in.findall(xpath_expr_refdefs % (pcb_layer, refdef), 
                                          namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                                      'svg':config.cfg['ns']['svg']})

            for refdef_text in refdef_texts:

                # Get refdef group location
                transform_data = utils.parseTransform(refdef_text.get('transform'))
                group_loc = transform_data['location']
                # Invert 'y' coordinate
                group_loc.y *= config.cfg['invert-y']


                # Get the refdef text path inside the refdef group
                refdef_path = refdef_text.find("svg:path", 
                                               namespaces={'svg':config.cfg['ns']['svg']})
                try:
                    transform_data = utils.parseTransform(refdef_path.get('transform'))
                except:
                    transform_data['location'] = Point(0,0)
                refdef_loc = transform_data['location']
                # Invert 'y' coordinate
                refdef_loc.y *= config.cfg['invert-y']

                # Current ('old') location of the component
                current_component_loc = utils.toPoint(comp_dict.get('location', [0, 0]))
                try:
                    current_refdef_loc = utils.toPoint(comp_dict['silkscreen']['refdef']['location'])
                except:
                    current_refdef_loc = Point()

                # TODO: this is an embarassing mess, but I have too much of
                # a headache to tidy it up!
                if pcb_layer == 'bottom':
                    current_refdef_loc.x = -current_refdef_loc.x
                diff = group_loc-current_component_loc
                new_refdef_loc = diff + current_refdef_loc
                if pcb_layer == 'bottom':
                    new_refdef_loc.x = -new_refdef_loc.x

                # Change the location in the dictionary
                if new_refdef_loc != current_refdef_loc:
                    try:
                        tmp = comp_dict['silkscreen']
                    except:
                        comp_dict['silkscreen'] = {}

                    try:
                        tmp = comp_dict['silkscreen']['refdef']
                    except:
                        comp_dict['silkscreen']['refdef'] = {}

                    comp_dict['silkscreen']['refdef']['location'] = [new_refdef_loc.x,
                                                                     new_refdef_loc.y] 


    # Save board config to file (everything is saved, not only the
    # component data)
    filename = os.path.join(config.cfg['locations']['boards'], 
                            config.cfg['name'], 
                            config.cfg['name'] + '.json')
    try:
        with open(filename, 'wb') as f:
            f.write(json.dumps(config.brd, sort_keys=True, indent=2))
    except:
        msg.error("Cannot save file %s" % filename)
 
    return






def extractRouting(svg_in):
    """
    Extracts routing from the the 'routing' SVG layers of each PCB layer.
    Inkscape SVG layers for each PCB ('top', 'bottom', etc.) layer.
    """

    # Open the routing file if it exists. The existing data is used
    # for stats displayed as PCBmodE is run. The file is then
    # overwritten.
    output_file = os.path.join(config.cfg['base-dir'],
                               config.cfg['name'] + '_routing.json')
    try:
        routing_dict_old = utils.dictFromJsonFile(output_file, False)
    except:
        routing_dict_old = {'routes': {}} 

    #---------------
    # Extract routes
    #---------------

    # Store extracted data here
    routing_dict = {}

    # The XPATH expression for extracting routes, but not vias
    xpath_expr = "//svg:g[@pcbmode:pcb-layer='%s']//svg:g[@pcbmode:sheet='routing']//svg:path[(@d) and not (@pcbmode:type='via')]"

    routes_dict = {}

    for pcb_layer in config.stk['layer-names']:
        routes = svg_in.xpath(xpath_expr % pcb_layer, 
                              namespaces={'pcbmode':config.cfg['ns']['pcbmode'], 
                                          'svg':config.cfg['ns']['svg']})

        for route in routes:
            route_dict = {}
            route_id = route.get('{'+config.cfg['ns']['pcbmode']+'}id')
            path = route.get('d')

            style_text = route.get('style') or ''
            
            # This hash digest provides a unique identifier for
            # the route based on its path, location, and style
            digest = utils.digest(path+
                                  #str(location.x)+
                                  #str(location.y)+
                                  style_text)

            try:
                routes_dict[pcb_layer][digest] = {}
            except:
                routes_dict[pcb_layer] = {}
                routes_dict[pcb_layer][digest] = {}
            routes_dict[pcb_layer][digest]['type'] = 'path'
            routes_dict[pcb_layer][digest]['value'] = path

            stroke_width = utils.getStyleAttrib(style_text, 'stroke-width')
            if stroke_width != None:
                # Sometimes Inkscape will add a 'px' suffix to the stroke-width 
                #property pf a path; this removes it
                stroke_width = stroke_width.rstrip('px')
                routes_dict[pcb_layer][digest]['style'] = 'stroke'
                routes_dict[pcb_layer][digest]['stroke-width'] = round(float(stroke_width), 4)

            custom_buffer = route.get('{'+config.cfg['ns']['pcbmode']+'}buffer-to-pour')
            if custom_buffer != None:
                routes_dict[pcb_layer][digest]['buffer-to-pour'] = float(custom_buffer)

            gerber_lp = route.get('{'+config.cfg['ns']['pcbmode']+'}gerber-lp')
            if gerber_lp != None:
                routes_dict[pcb_layer][digest]['gerber-lp'] = gerber_lp



    routing_dict['routes'] = routes_dict

    # Create simple stats and display them
    total = 0
    total_old = 0
    new = 0
    existing = 0
    for pcb_layer in config.stk['layer-names']:
        try:
            total += len(routing_dict['routes'][pcb_layer])
        except:
            pass
        try:
            new_dict = routing_dict['routes'][pcb_layer]
        except:
            new_dict = {}
        try:
            old_dict = routing_dict_old['routes'][pcb_layer]
        except:
            old_dict = {}
        for key in new_dict:
            if key not in old_dict:
                new += 1
            else:
                existing += 1

    for pcb_layer in config.stk['layer-names']:
        total_old += len(old_dict)

    message = "Extracted %s routes; %s new (or modified), %s existing" % (total, new, existing)
    if total_old > total:
        message += ", %s removed" % (total_old - total)
    msg.subInfo(message)


    #-------------------------------
    # Extract vias
    #-------------------------------

    xpath_expr_place = '//svg:g[@pcbmode:pcb-layer="%s"]//svg:g[@pcbmode:sheet="placement"]//svg:g[@pcbmode:type="via"]'

    vias_dict = {}

    for pcb_layer in config.stk['surface-layer-names']:
        
        # Find all markers
        markers = svg_in.findall(xpath_expr_place % pcb_layer, 
                                 namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                             'svg':config.cfg['ns']['svg']})

        for marker in markers:
            transform_data = utils.parseTransform(marker.get('transform'))
            location = transform_data['location']
            # Invert 'y' coordinate
            location.y *= config.cfg['invert-y']

            # Change component rotation if needed
            if transform_data['type'] == 'matrix':
                rotate = transform_data['rotate']
                rotate = utils.niceFloat((rotate) % 360)
                
            digest = utils.digest("%s%s" % (location.x, location.y))

            # Define a via, just like any other component, but disable
            # placement of refdef
            vias_dict[digest] = {}
            vias_dict[digest]['footprint'] = marker.get('{'+config.cfg['ns']['pcbmode']+'}footprint')
            vias_dict[digest]['location'] = [utils.niceFloat(location.x),
                                             utils.niceFloat(location.y)]
            vias_dict[digest]['layer'] = 'top'


    routing_dict['vias'] = vias_dict

    # Display stats
    if len(vias_dict) == 0:
        msg.subInfo("No vias found")
    elif len(vias_dict) == 1:
        msg.subInfo("Extracted 1 via")
    else:
        msg.subInfo("Extracted %s vias" % (len(vias_dict)))
    

    # Save extracted routing into routing file
    try:
        with open(output_file, 'wb') as f:
            f.write(json.dumps(routing_dict, sort_keys=True, indent=2))
    except:
        msg.error("Cannot save file %s" % output_file)

    return






def extractDocs(svg_in):
    """
    Extracts the position of the documentation elements and updates
    the board's json
    """

    # Get copper refdef shape groups from SVG data
    xpath_expr = '//svg:g[@pcbmode:sheet="documentation"]//svg:g[@pcbmode:type="module-shapes"]'
    docs = svg_in.findall(xpath_expr, 
                          namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                      'svg':config.cfg['ns']['svg']})

    
    for doc in docs:
        doc_key = doc.get('{'+config.cfg['ns']['pcbmode']+'}doc-key')
        translate_data = utils.parseTransform(doc.get('transform'))
        location = translate_data['location']
        location.y *= config.cfg['invert-y']

        current_location = utils.toPoint(config.brd['documentation'][doc_key]['location'])
        if current_location != location:
            config.brd['documentation'][doc_key]['location'] = [location.x, location.y] 
            msg.subInfo("Found new location ([%s, %s]) for '%s'" % (location.x, location.y, doc_key))


    # Extract drill index location
    xpath_expr = '//svg:g[@pcbmode:sheet="drills"]//svg:g[@pcbmode:type="drill-index"]'
    drill_index = svg_in.find(xpath_expr, 
                              namespaces={'pcbmode':config.cfg['ns']['pcbmode'],
                                          'svg':config.cfg['ns']['svg']})    
    transform_dict = utils.parseTransform(drill_index.get('transform'))
    location = transform_dict['location']
    location.y *= config.cfg['invert-y']

    # Modify the location in the board's config file. If a
    # 'drill-index' field doesn't exist, create it
    drill_index_dict = config.brd.get('drill-index') 
    if drill_index_dict == None:
        config.brd['drill-index'] = {}
    config.brd['drill-index']['location'] = [location.x, location.y]

        
    # Save board config to file (everything is saved, not only the
    # component data)
    filename = os.path.join(config.cfg['locations']['boards'], 
                            config.cfg['name'], 
                            config.cfg['name'] + '.json')
    try:
        with open(filename, 'wb') as f:
            f.write(json.dumps(config.brd, sort_keys=True, indent=2))
    except:
        msg.error("Cannot save file %s" % filename)
